from datetime import datetime, timedelta, timezone
import hmac
import re as _re
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.datetime_utils import to_naive_utc_datetime
from app.core.rate_limit import (
    AUTH_RATE_LIMIT_ERROR,
    RateLimitPolicy,
    build_scope_key,
    enforce_rate_limits,
    get_client_ip,
    get_redis_client,
    hash_key_part,
)
from app.core.security import (
    create_admin_webauthn_recovery_token,
    create_access_token,
    create_mfa_session_token,
    create_refresh_token,
    get_password_hash,
    hash_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.api.deps import get_current_user, enforce_not_banned
from app.models.email_change_token import EmailChangeToken
from app.models.user import User, UserStatus
from app.models.invite import InviteCode
from app.models.invite_campaign import InviteCampaign
from app.models.invite_usage import InviteUsage
from app.models.refresh_token import RefreshToken
from app.models.webauthn_credential import WebAuthnCredential
from app.services.account_security import (
    consume_email_change_token,
    consume_email_verification_token,
    consume_password_reset_token,
    describe_client_device,
    complete_password_reset,
    get_email_change_token_by_secret,
    get_email_verification_token_by_secret,
    get_password_reset_token_by_secret,
    issue_email_change_token,
    issue_email_verification_token,
    issue_password_reset_token,
    list_active_sessions_for_user,
    mark_email_verified,
    mask_email,
    normalize_email,
    normalize_login_identifier,
    revoke_active_email_change_tokens_for_user,
    revoke_all_password_reset_tokens_for_user,
    revoke_refresh_tokens_for_user,
    send_email_change_email,
    send_password_reset_email,
    send_verification_email,
)
from app.services.audit import write_audit_log
from app.services.admin_security import (
    consume_admin_password_reset_token,
    get_admin_password_reset_token_by_secret,
    revoke_all_refresh_tokens_for_user,
)
from app.services.invite_flow import resolve_inviter_user, validate_invite_state
from app.services.invite_campaigns import get_campaign_counts
from app.services.signup_idempotency import SignupIdempotencyService
from app.services.staff_permissions import derive_admin_response_flags, staff_session_requires_security_key
from app.schemas.user import UserCreate, UserLogin, UserRead
from app.schemas.auth import (
    AdminPasswordResetCompleteRequest,
    AdminWebAuthnRecoveryTokenResponse,
    EmailChangeCompleteRequest,
    EmailChangeRequest,
    EmailActionRequest,
    EmailTokenCompleteRequest,
    EmailTokenCompletionResponse,
    LogoutRequest,
    NeutralActionResponse,
    OtherSessionsRevokeResponse,
    PendingEmailVerificationResponse,
    PasswordConfirmRequest,
    RefreshTokenRequest,
    SessionListResponse,
    SessionRead,
    SessionRevokeResponse,
    Token,
)

router = APIRouter(tags=["auth"])
COOKIE_SESSION_TRANSPORT_HEADER = "x-session-transport"
COOKIE_SESSION_TRANSPORT_VALUE = "cookie"
_REQUEST_KEY_RE = _re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    _re.IGNORECASE,
)


def _prefers_cookie_refresh(request: Request) -> bool:
    return request.headers.get(COOKIE_SESSION_TRANSPORT_HEADER, "").lower() == COOKIE_SESSION_TRANSPORT_VALUE


def _build_token_response(tokens: Token, request: Request, *, user: User | None = None) -> Token:
    user_payload = _build_user_read_response(user) if user is not None else None
    if _prefers_cookie_refresh(request):
        return Token(access_token=tokens.access_token, refresh_token=None, user=user_payload)
    return Token(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        user=user_payload,
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        expires=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        path="/api/auth",
    )


def _get_refresh_token_from_request(
    request: Request,
    refresh_token: str | None,
) -> str:
    token = refresh_token or request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _create_access_token_for_user(user: User, session_id: int | None) -> str:
    return create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "sid": str(session_id) if session_id is not None else None,
        }
    )


def _get_device_fingerprint(request: Request) -> str:
    """Return a hex fingerprint derived from User-Agent and stable client
    hint headers (Accept-Language, Accept-Encoding, Sec-CH-UA-Platform).

    IP address is intentionally excluded: mobile and installed-PWA clients
    frequently change network interfaces (WiFi → cellular and back), which
    would produce a different IP on every reconnect and cause legitimate
    sessions to be invalidated.  The remaining headers still provide
    meaningful fingerprinting signal against session-token theft without
    producing false positives for roaming users.
    """
    import hashlib
    ua = request.headers.get("user-agent", "")
    lang = request.headers.get("accept-language", "")
    encoding = request.headers.get("accept-encoding", "")
    platform = request.headers.get("sec-ch-ua-platform", "")
    raw = f"{ua}|{lang}|{encoding}|{platform}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def _save_refresh_token(
    db: AsyncSession,
    user_id: int,
    refresh_token: str,
    *,
    mfa_satisfied: bool,
    device_fingerprint: str | None = None,
    device_label: str | None = None,
) -> RefreshToken:
    """Save a refresh token with an optional device fingerprint."""
    token_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    db_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        mfa_satisfied=mfa_satisfied,
        last_used_at=datetime.now(timezone.utc),
        device_label=device_label,
        device_fingerprint=device_fingerprint,
    )
    db.add(db_token)
    await db.flush()
    return db_token


async def _issue_session_tokens(
    db: AsyncSession,
    *,
    user: User,
    request: Request,
    mfa_satisfied: bool,
) -> tuple[Token, RefreshToken]:
    refresh_token = create_refresh_token()
    refresh_record = await _save_refresh_token(
        db,
        user.id,
        refresh_token,
        mfa_satisfied=mfa_satisfied,
        device_fingerprint=_get_device_fingerprint(request),
        device_label=describe_client_device(request),
    )
    access_token = _create_access_token_for_user(user, refresh_record.id)
    return Token(access_token=access_token, refresh_token=refresh_token), refresh_record


def _get_current_session_id(current_user: User) -> int | None:
    raw_value = getattr(current_user, "_current_session_id", None)
    if raw_value is None:
        return None
    return int(raw_value)


def _build_user_read_response(user: User) -> UserRead:
    is_admin, admin_role = derive_admin_response_flags(user)
    return UserRead.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "cover_url": user.cover_url,
            "bio": user.bio,
            "location": user.location,
            "website": user.website,
            "created_at": user.created_at,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "email_verified_at": user.email_verified_at,
            "is_admin": is_admin,
            "admin_role": admin_role,
            "status": user.status,
            "banned_at": user.banned_at,
            "ban_reason": user.ban_reason,
            "status_reason": user.status_reason,
            "status_changed_at": user.status_changed_at,
            "status_changed_by_user_id": user.status_changed_by_user_id,
            "invited_by_user_id": user.invited_by_user_id,
            "invite_id_used": user.invite_id_used,
            "inviter": user.inviter,
        }
    )


def _require_sensitive_password_confirmation(current_user: User, candidate_password: str) -> None:
    if not verify_password(candidate_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )


def _login_limit_policies(request: Request, username_or_email: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    identifier_key = hash_key_part(username_or_email)
    return [
        RateLimitPolicy(
            name="auth-login-ip",
            limit=8,
            window_seconds=300,
            key=build_scope_key("auth", "login", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="auth-login-identifier",
            limit=5,
            window_seconds=600,
            key=build_scope_key("auth", "login", "identifier", ip_key, identifier_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _register_limit_policies(request: Request, invite_code: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    invite_key = hash_key_part(invite_code)
    return [
        RateLimitPolicy(
            name="auth-register-ip",
            limit=3,
            window_seconds=3600,
            key=build_scope_key("auth", "register", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="auth-register-invite",
            limit=2,
            window_seconds=1800,
            key=build_scope_key("auth", "register", "invite", ip_key, invite_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _verification_request_limit_policies(request: Request, email: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    email_key = hash_key_part(email)
    return [
        RateLimitPolicy(
            name="verify-email-request-ip",
            limit=5,
            window_seconds=3600,
            key=build_scope_key("auth", "verify-email", "request", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="verify-email-request-email",
            limit=3,
            window_seconds=3600,
            key=build_scope_key("auth", "verify-email", "request", "email", email_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _verification_complete_limit_policies(request: Request, token: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    token_key = hash_key_part(token)
    return [
        RateLimitPolicy(
            name="verify-email-complete-ip",
            limit=10,
            window_seconds=900,
            key=build_scope_key("auth", "verify-email", "complete", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="verify-email-complete-token",
            limit=5,
            window_seconds=900,
            key=build_scope_key("auth", "verify-email", "complete", "token", token_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _password_reset_request_limit_policies(request: Request, email: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    email_key = hash_key_part(email)
    return [
        RateLimitPolicy(
            name="password-reset-request-ip",
            limit=5,
            window_seconds=3600,
            key=build_scope_key("auth", "password-reset", "request", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="password-reset-request-email",
            limit=3,
            window_seconds=3600,
            key=build_scope_key("auth", "password-reset", "request", "email", email_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _password_reset_complete_limit_policies(request: Request, token: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    token_key = hash_key_part(token)
    return [
        RateLimitPolicy(
            name="password-reset-complete-ip",
            limit=10,
            window_seconds=900,
            key=build_scope_key("auth", "password-reset", "complete", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="password-reset-complete-token",
            limit=5,
            window_seconds=900,
            key=build_scope_key("auth", "password-reset", "complete", "token", token_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _pending_verification_response(user: User, *, message: str) -> PendingEmailVerificationResponse:
    return PendingEmailVerificationResponse(
        message=message,
        email=user.email,
        masked_email=mask_email(user.email) or user.email,
    )


def _refresh_limit_policies(request: Request, raw_refresh_token: str) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    token_key = hash_key_part(raw_refresh_token)
    return [
        RateLimitPolicy(
            name="auth-refresh-ip",
            limit=30,
            window_seconds=600,
            key=build_scope_key("auth", "refresh", "ip", ip_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="auth-refresh-token",
            limit=12,
            window_seconds=300,
            key=build_scope_key("auth", "refresh", "token", ip_key, token_key),
            message=AUTH_RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _admin_webauthn_recovery_identifier() -> str | None:
    raw_identifier = settings.ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER
    if raw_identifier is None:
        return None
    identifier = raw_identifier.strip().lower()
    return identifier or None


async def _admin_webauthn_recovery_is_eligible(db: AsyncSession, user: User | None) -> bool:
    if user is None:
        return False
    if not staff_session_requires_security_key(user):
        return False
    if user.email_verified_at is None or user.must_change_password:
        return False
    if user.status in {UserStatus.BANNED, UserStatus.SUSPENDED} or not user.is_active:
        return False

    webauthn_result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .limit(1)
    )
    return webauthn_result.scalar_one_or_none() is None


def _logout_limit_policies(request: Request) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="auth-logout-ip",
            limit=20,
            window_seconds=60,
            key=build_scope_key("auth", "logout", "ip", hash_key_part(get_client_ip(request))),
            message=AUTH_RATE_LIMIT_ERROR,
        ),
    ]


def _session_list_limit_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="auth-sessions-list-user",
            limit=30,
            window_seconds=60,
            key=build_scope_key("auth", "sessions", "list", "user", user_id),
            message=AUTH_RATE_LIMIT_ERROR,
        ),
    ]


def _session_revoke_limit_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="auth-sessions-revoke-user",
            limit=10,
            window_seconds=60,
            key=build_scope_key("auth", "sessions", "revoke", "user", user_id),
            message=AUTH_RATE_LIMIT_ERROR,
        ),
    ]


def _session_revoke_others_limit_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="auth-sessions-revoke-others-user",
            limit=5,
            window_seconds=60,
            key=build_scope_key("auth", "sessions", "revoke-others", "user", user_id),
            message=AUTH_RATE_LIMIT_ERROR,
        ),
    ]


@router.post("/register", response_model=PendingEmailVerificationResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    response: Response,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user with an invite code.
    
    - Validates the invite code (active, not expired, unused)
    - Creates the user
    - Updates the invite code usage
    - Returns JWT access token and refresh token
    """
    normalized_email = normalize_email(str(user_data.email))
    _raw_request_key = (request.headers.get("X-Signup-Request-Key") or user_data.request_key or "").strip()
    request_key = _raw_request_key if _raw_request_key and len(_raw_request_key) <= 64 and _REQUEST_KEY_RE.match(_raw_request_key) else None
    redis_client = await get_redis_client()
    idempotency = SignupIdempotencyService(redis_client)

    if request_key is not None:
        cached_result = await idempotency.get_cached_result(request_key)
        if cached_result is not None:
            return PendingEmailVerificationResponse(**cached_result)

    request_lock_acquired, fingerprint_lock_acquired = await idempotency.acquire_locks(
        request_key,
        user_data.invite_code,
        normalized_email,
        user_data.username,
    )
    if not request_lock_acquired or not fingerprint_lock_acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration is already in progress. Please wait a moment.",
        )

    try:
        await enforce_rate_limits(request, _register_limit_policies(request, user_data.invite_code))
        if len(user_data.invite_code) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invite code is invalid or unavailable.",
            )

        result = await db.execute(
            select(InviteCode)
            .options(
                selectinload(InviteCode.created_by_user),
                selectinload(InviteCode.assigned_to_user),
                selectinload(InviteCode.campaign),
            )
            .where(InviteCode.code == user_data.invite_code)
            .with_for_update()
        )
        invite = result.scalar_one_or_none()

        if not invite:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invite code is invalid or unavailable.",
            )

        campaign_generated_count = None
        campaign_consumed_count = None
        if invite.campaign_id is not None and invite.campaign is not None:
            campaign_result = await db.execute(
                select(InviteCampaign)
                .where(InviteCampaign.id == invite.campaign_id)
                .with_for_update()
            )
            invite.campaign = campaign_result.scalar_one()
            campaign_counts = await get_campaign_counts(db, invite.campaign_id)
            campaign_generated_count = campaign_counts["generated_count"]
            campaign_consumed_count = campaign_counts["consumed_count"]

        violation = validate_invite_state(
            invite,
            campaign_generated_count=campaign_generated_count,
            campaign_consumed_count=campaign_consumed_count,
        )
        if violation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=violation.public_message,
            )

        result = await db.execute(
            select(User).where(
                or_(
                    User.username == user_data.username,
                    User.email == normalized_email,
                )
            )
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration details already in use",
            )

        inviter = resolve_inviter_user(invite)
        registration_time = datetime.now(timezone.utc)

        new_user = User(
            username=user_data.username,
            display_name=user_data.display_name,
            email=normalized_email,
            password_hash=get_password_hash(user_data.password),
            is_active=True,
            email_verified_at=None,
            status=UserStatus.ACTIVE,
            invited_by_user_id=inviter.id if inviter else None,
            invite_id_used=invite.id,
        )

        new_user.staff_permission = None
        db.add(new_user)
        await db.flush()

        db.add(
            InviteUsage(
                invite_id=invite.id,
                used_by_user_id=new_user.id,
                used_at=registration_time,
            )
        )

        invite.current_uses = 1
        invite.used_by_user_id = new_user.id
        invite.used_at = registration_time
        invite.max_uses = 1
        invite.is_active = False

        verification_result = await issue_email_verification_token(
            db,
            user=new_user,
            request=request,
        )
        await write_audit_log(
            db,
            action="campaign_invite_consumed" if invite.campaign_id else "invite.redeem",
            actor_user=new_user,
            target_type="invite_campaign" if invite.campaign_id else "invite",
            target_id=invite.campaign_id if invite.campaign_id else invite.id,
            before={"invite_status": "active"},
            after={
                "invite_id": invite.id,
                "campaign_id": invite.campaign_id,
                "used_by_user_id": new_user.id,
                "used_at": registration_time.isoformat(),
                "lineage_invited_by_user_id": new_user.invited_by_user_id,
            },
            request=request,
            success=True,
        )
        await write_audit_log(
            db,
            action="email_verification_token_issued",
            actor_user=new_user,
            target_type="user",
            target_id=new_user.id,
            after={
                "token_id": verification_result.token_id,
                "masked_email": mask_email(new_user.email),
                "expires_at": verification_result.expires_at.isoformat(),
                "invalidated_prior_tokens": verification_result.invalidated_count,
                "source": "registration",
            },
            request=request,
            success=True,
        )
        await db.commit()
        pending_response = _pending_verification_response(
            new_user,
            message="Account created. Verify your email before signing in.",
        )
        await idempotency.cache_result(request_key, pending_response.model_dump())
        try:
            await send_verification_email(to_email=new_user.email, secret=verification_result.raw_secret)
        except Exception:
            await write_audit_log(
                db,
                action="email_verification_delivery_failed",
                actor_user=new_user,
                target_type="user",
                target_id=new_user.id,
                after={"masked_email": mask_email(new_user.email), "source": "registration"},
                request=request,
                success=False,
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Account created, but the verification email could not be sent. Please request a new verification email.",
            )
        _clear_refresh_cookie(response)
        return pending_response
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        await write_audit_log(
            db,
            action="register.duplicate",
            actor_user=None,
            after={"attempted_username": user_data.username, "masked_email": mask_email(normalized_email)},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration could not be completed. Please verify the username, email, and invite code."
        )
    finally:
        await idempotency.release_locks(
            request_key,
            user_data.invite_code,
            normalized_email,
            user_data.username,
        )


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    login_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with username or email and password.

    - Finds user by username or email
    - Verifies password
    - If user has WebAuthn credentials → returns 202 with mfa_required=true
    - If user has no WebAuthn credentials → returns JWT access token and refresh token
    """
    normalized_identifier = normalize_login_identifier(login_data.username)
    await enforce_rate_limits(request, _login_limit_policies(request, normalized_identifier))

    # Find user by username or email
    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter), selectinload(User.staff_permission))
        .where(
            or_(
                User.username == login_data.username,
                User.email == normalized_identifier
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        await write_audit_log(
            db,
            action="login.failed",
            actor_user=None,
            after={
                "attempted_identifier": mask_email(normalized_identifier) if "@" in normalized_identifier else normalized_identifier,
                "reason": "user_not_found",
            },
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(login_data.password, user.password_hash):
        await write_audit_log(
            db,
            action="login.failed",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"reason": "wrong_password"},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    try:
        enforce_not_banned(user)
    except HTTPException:
        await write_audit_log(
            db,
            action="login.banned_attempt",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"status": user.status.value},
            request=request,
            success=False,
        )
        await db.commit()
        raise

    if user.must_change_password:
        await write_audit_log(
            db,
            action="login.password_reset_required",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"must_change_password": True},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password reset required before sign in",
        )

    if user.email_verified_at is None:
        await write_audit_log(
            db,
            action="login.unverified_email",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"masked_email": mask_email(user.email)},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "EMAIL_VERIFICATION_REQUIRED",
                "message": "Verify your email before signing in.",
                "masked_email": mask_email(user.email),
            },
        )
    
    # --- WebAuthn / MFA gate ---
    webauthn_result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .limit(1)
    )
    has_webauthn = webauthn_result.scalar_one_or_none() is not None

    if has_webauthn:
        mfa_token = await create_mfa_session_token(
            user.id,
            ttl_minutes=settings.WEBAUTHN_MFA_TOKEN_TTL_MINUTES,
        )
        await write_audit_log(
            db,
            action="login.mfa_required",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            request=request,
            success=True,
        )
        await db.commit()
        return JSONResponse(
            status_code=202,
            content={"mfa_required": True, "mfa_session_token": mfa_token},
        )

    tokens, refresh_record = await _issue_session_tokens(
        db,
        user=user,
        request=request,
        mfa_satisfied=False,
    )
    await write_audit_log(
        db,
        action="login",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        request=request,
        session_id=refresh_record.id,
        success=True,
    )

    await db.commit()

    if _prefers_cookie_refresh(request):
        _set_refresh_cookie(response, tokens.refresh_token)

    return _build_token_response(tokens, request, user=user)


@router.post("/admin-recovery/webauthn-token", response_model=AdminWebAuthnRecoveryTokenResponse)
async def issue_admin_webauthn_recovery_token_route(
    request: Request,
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _login_limit_policies(request, payload.username))

    configured_identifier = _admin_webauthn_recovery_identifier()
    generic_denial = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin WebAuthn recovery is not available for this account.",
    )

    if not settings.ENABLE_ADMIN_WEBAUTHN_RECOVERY or configured_identifier is None:
        raise generic_denial

    if not hmac.compare_digest(payload.username, configured_identifier):
        raise generic_denial

    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(
            or_(
                User.username == payload.username,
                User.email == payload.username,
            )
        )
    )
    user = result.scalar_one_or_none()
    password_ok = user is not None and verify_password(payload.password, user.password_hash)
    eligible = await _admin_webauthn_recovery_is_eligible(db, user) if password_ok else False

    if not password_ok or not eligible:
        await write_audit_log(
            db,
            action="admin_webauthn_recovery_denied",
            actor_user=user,
            target_type="user" if user else None,
            target_id=user.id if user else None,
            after={"identifier": payload.username},
            request=request,
            success=False,
        )
        await db.commit()
        raise generic_denial

    recovery_token = await create_admin_webauthn_recovery_token(
        user.id,
        ttl_minutes=settings.ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES,
    )
    await write_audit_log(
        db,
        action="admin_webauthn_recovery_token_issued",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        after={"identifier": payload.username},
        request=request,
        success=True,
    )
    await db.commit()
    return AdminWebAuthnRecoveryTokenResponse(
        recovery_token=recovery_token,
        expires_in_seconds=settings.ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES * 60,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_request: RefreshTokenRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using a valid refresh token.
    
    - Validates the refresh token
    - Revokes the old refresh token (rotation)
    - Issues a new access token and new refresh token
    """
    raw_refresh_token = _get_refresh_token_from_request(request, token_request.refresh_token)
    await enforce_rate_limits(request, _refresh_limit_policies(request, raw_refresh_token))
    token_hash = hash_refresh_token(raw_refresh_token)
    
    # Find the refresh token in database
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one_or_none()
    
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if token is revoked
    if db_token.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if token is expired
    if db_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get the user
    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter), selectinload(User.staff_permission))
        .where(User.id == db_token.user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    enforce_not_banned(user)
    if user.email_verified_at is None:
        db_token.revoked = True
        await write_audit_log(
            db,
            action="refresh.unverified_email",
            actor_user=user,
            target_type="session",
            target_id=db_token.id,
            after={"masked_email": mask_email(user.email)},
            request=request,
            session_id=db_token.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "EMAIL_VERIFICATION_REQUIRED",
                "message": "Verify your email before continuing.",
                "masked_email": mask_email(user.email),
            },
        )

    # Device fingerprint check: revoke if the stable client-header fingerprint changes
    current_fingerprint = _get_device_fingerprint(request)
    if db_token.device_fingerprint and db_token.device_fingerprint != current_fingerprint:
        db_token.revoked = True
        await write_audit_log(
            db,
            action="refresh.device_mismatch",
            actor_user=user,
            target_type="session",
            target_id=db_token.id,
            after={"reason": "device_mismatch"},
            request=request,
            session_id=db_token.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Revoke the old refresh token (rotation)
    db_token.revoked = True
    db_token.last_used_at = datetime.now(timezone.utc)

    tokens, _ = await _issue_session_tokens(
        db,
        user=user,
        request=request,
        mfa_satisfied=db_token.mfa_satisfied,
    )

    await db.commit()

    if _prefers_cookie_refresh(request):
        _set_refresh_cookie(response, tokens.refresh_token)

    return _build_token_response(tokens, request, user=user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    logout_request: LogoutRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Logout by revoking the refresh token.
    
    - Revokes the provided refresh token
    """
    await enforce_rate_limits(request, _logout_limit_policies(request))
    raw_refresh_token = logout_request.refresh_token or request.cookies.get(settings.REFRESH_COOKIE_NAME)

    if raw_refresh_token is None:
        _clear_refresh_cookie(response)
        return None

    token_hash = hash_refresh_token(raw_refresh_token)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one_or_none()

    actor_user = None
    session_id = None
    if db_token:
        actor_user_result = await db.execute(
            select(User)
            .options(selectinload(User.staff_permission))
            .where(User.id == db_token.user_id)
        )
        actor_user = actor_user_result.scalar_one_or_none()
        session_id = db_token.id
        if not db_token.revoked:
            db_token.revoked = True

    await write_audit_log(
        db,
        action="logout",
        actor_user=actor_user,
        target_type="session",
        target_id=session_id,
        request=request,
        session_id=session_id,
        success=True,
    )
    await db.commit()
    _clear_refresh_cookie(response)

    return None


@router.get("/sessions", response_model=SessionListResponse)
async def list_my_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _session_list_limit_policies(current_user.id))
    current_session_id = _get_current_session_id(current_user)
    sessions = await list_active_sessions_for_user(db, current_user.id)
    return SessionListResponse(
        sessions=[
            SessionRead(
                id=session.id,
                is_current=current_session_id == session.id,
                created_at=session.created_at.isoformat(),
                last_used_at=session.last_used_at.isoformat() if session.last_used_at else None,
                expires_at=session.expires_at.isoformat(),
                device_label=session.device_label,
            )
            for session in sessions
        ]
    )


@router.post("/sessions/{session_id}/revoke", response_model=SessionRevokeResponse)
async def revoke_session(
    session_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _session_revoke_limit_policies(current_user.id))
    current_session_id = _get_current_session_id(current_user)
    if current_session_id == session_id:
        await write_audit_log(
            db,
            action="session_revoke_denied",
            actor_user=current_user,
            target_type="session",
            target_id=session_id,
            after={"reason": "current_session_revoke_blocked"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current session cannot be revoked from this endpoint. Sign out instead.",
        )

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == current_user.id,
        )
    )
    target_session = result.scalar_one_or_none()
    if target_session is None or target_session.revoked:
        await write_audit_log(
            db,
            action="session_revoke_denied",
            actor_user=current_user,
            target_type="session",
            target_id=session_id,
            after={"reason": "session_not_found_or_inactive"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    target_session.revoked = True
    await write_audit_log(
        db,
        action="session_revoked",
        actor_user=current_user,
        target_type="session",
        target_id=target_session.id,
        after={"reason": "user_revoke_single_session"},
        request=request,
        session_id=current_session_id,
        success=True,
    )
    await db.commit()
    return SessionRevokeResponse(revoked_session_id=target_session.id)


@router.post("/sessions/revoke-others", response_model=OtherSessionsRevokeResponse)
async def revoke_other_sessions(
    request: Request,
    payload: PasswordConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _session_revoke_others_limit_policies(current_user.id))
    current_session_id = _get_current_session_id(current_user)
    if current_session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session context missing. Sign in again.")

    try:
        _require_sensitive_password_confirmation(current_user, payload.current_password)
    except HTTPException:
        await write_audit_log(
            db,
            action="session_revoke_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "step_up_password_invalid", "scope": "other_sessions"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise

    revocation = await revoke_refresh_tokens_for_user(
        db,
        user_id=current_user.id,
        exclude_session_ids={current_session_id},
    )
    await write_audit_log(
        db,
        action="other_sessions_revoked",
        actor_user=current_user,
        target_type="user",
        target_id=current_user.id,
        after={
            "revoked_session_count": revocation.revoked_count,
            "preserved_session_id": current_session_id,
        },
        request=request,
        session_id=current_session_id,
        success=True,
    )
    await db.commit()
    return OtherSessionsRevokeResponse(revoked_session_count=revocation.revoked_count)


@router.post("/verify-email/request", response_model=NeutralActionResponse)
async def request_email_verification(
    request: Request,
    payload: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email
    await enforce_rate_limits(request, _verification_request_limit_policies(request, normalized_email))
    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.email == normalized_email)
    )
    user = result.scalar_one_or_none()

    response = NeutralActionResponse(message="If the account is eligible, a verification email will be sent shortly.")

    if user is None:
        await write_audit_log(
            db,
            action="email_verification_resend_denied",
            actor_user=None,
            after={"masked_email": mask_email(normalized_email), "reason": "user_not_found"},
            request=request,
            success=False,
        )
        await db.commit()
        return response

    if user.email_verified_at is not None:
        await write_audit_log(
            db,
            action="email_verification_resend_denied",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"masked_email": mask_email(user.email), "reason": "already_verified"},
            request=request,
            success=False,
        )
        await db.commit()
        return response

    verification_result = await issue_email_verification_token(db, user=user, request=request)
    await write_audit_log(
        db,
        action="email_verification_resent",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        after={
            "token_id": verification_result.token_id,
            "masked_email": mask_email(user.email),
            "expires_at": verification_result.expires_at.isoformat(),
            "invalidated_prior_tokens": verification_result.invalidated_count,
        },
        request=request,
        success=True,
    )
    await db.commit()
    try:
        await send_verification_email(to_email=user.email, secret=verification_result.raw_secret)
    except Exception:
        await write_audit_log(
            db,
            action="email_verification_delivery_failed",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"masked_email": mask_email(user.email), "source": "resend"},
            request=request,
            success=False,
        )
        await db.commit()
    return response


@router.post("/verify-email/complete", response_model=EmailTokenCompletionResponse)
async def complete_email_verification(
    request: Request,
    payload: EmailTokenCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _verification_complete_limit_policies(request, payload.token))
    verification_token = await get_email_verification_token_by_secret(db, payload.token)
    if verification_token is None:
        await write_audit_log(
            db,
            action="email_verification_resend_denied",
            actor_user=None,
            after={"reason": "token_not_found"},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification link")

    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == verification_token.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification link")

    try:
        await consume_email_verification_token(db, verification_token)
    except HTTPException:
        await write_audit_log(
            db,
            action="email_verification_resend_denied",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"reason": "token_inactive", "token_id": verification_token.id},
            request=request,
            success=False,
        )
        await db.commit()
        raise

    if user.email_verified_at is not None:
        await write_audit_log(
            db,
            action="email_verification_resend_denied",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"reason": "already_verified", "token_id": verification_token.id},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification link")

    invalidated_count = await mark_email_verified(db, user=user, token=verification_token)
    await write_audit_log(
        db,
        action="email_verified",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        after={
            "token_id": verification_token.id,
            "masked_email": mask_email(user.email),
            "invalidated_remaining_tokens": invalidated_count,
            "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        },
        request=request,
        success=True,
    )
    await db.commit()
    return EmailTokenCompletionResponse(status="verified", message="Email verified. You can sign in now.")


@router.post("/email-change/request", response_model=NeutralActionResponse)
async def request_email_change(
    request: Request,
    payload: EmailChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_session_id = _get_current_session_id(current_user)
    response = NeutralActionResponse(message="If the new email is eligible, a confirmation link will be sent shortly.")

    try:
        _require_sensitive_password_confirmation(current_user, payload.current_password)
    except HTTPException:
        await write_audit_log(
            db,
            action="email_change_request_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "step_up_password_invalid"},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        raise

    if payload.new_email == current_user.email:
        await write_audit_log(
            db,
            action="email_change_request_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "same_email", "masked_email": mask_email(payload.new_email)},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        return response

    existing_user = await db.execute(select(User).where(User.email == payload.new_email))
    if existing_user.scalar_one_or_none() is not None:
        await write_audit_log(
            db,
            action="email_change_request_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "email_in_use", "masked_email": mask_email(payload.new_email)},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
        return response

    change_result = await issue_email_change_token(
        db,
        user=current_user,
        new_email=payload.new_email,
        request=request,
    )
    await write_audit_log(
        db,
        action="email_change_requested",
        actor_user=current_user,
        target_type="user",
        target_id=current_user.id,
        after={
            "token_id": change_result.token_id,
            "masked_new_email": mask_email(payload.new_email),
            "expires_at": change_result.expires_at.isoformat(),
            "invalidated_prior_tokens": change_result.invalidated_count,
        },
        request=request,
        session_id=current_session_id,
        success=True,
    )
    await db.commit()
    try:
        await send_email_change_email(to_email=payload.new_email, secret=change_result.raw_secret)
    except Exception:
        await write_audit_log(
            db,
            action="email_change_request_denied",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"reason": "delivery_failed", "masked_new_email": mask_email(payload.new_email)},
            request=request,
            session_id=current_session_id,
            success=False,
        )
        await db.commit()
    return response


@router.post("/email-change/complete", response_model=EmailTokenCompletionResponse)
async def complete_email_change(
    request: Request,
    payload: EmailChangeCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    email_change_token = await get_email_change_token_by_secret(db, payload.token)
    if email_change_token is None:
        await write_audit_log(
            db,
            action="email_change_complete_denied",
            actor_user=None,
            after={"reason": "token_not_found"},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired email change token")

    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == email_change_token.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired email change token")

    duplicate_user = await db.execute(
        select(User).where(
            User.email == email_change_token.pending_email,
            User.id != user.id,
        )
    )
    if duplicate_user.scalar_one_or_none() is not None:
        email_change_token.revoked_at = datetime.now(timezone.utc)
        await write_audit_log(
            db,
            action="email_change_complete_denied",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"reason": "email_in_use", "token_id": email_change_token.id},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired email change token")

    previous_email = user.email
    try:
        now = await consume_email_change_token(db, email_change_token)
    except HTTPException:
        await write_audit_log(
            db,
            action="email_change_complete_denied",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"reason": "token_inactive", "token_id": email_change_token.id},
            request=request,
            success=False,
        )
        await db.commit()
        raise

    user.email = email_change_token.pending_email
    user.email_verified_at = to_naive_utc_datetime(now)
    invalidated_pending_changes = await revoke_active_email_change_tokens_for_user(db, user.id)
    revoked_sessions = await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="email_change_completed",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        before={"masked_old_email": mask_email(previous_email)},
        after={
            "masked_new_email": mask_email(user.email),
            "token_id": email_change_token.id,
            "invalidated_pending_changes": invalidated_pending_changes,
            "revoked_session_count": revoked_sessions,
            "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        },
        request=request,
        success=True,
    )
    await db.commit()
    return EmailTokenCompletionResponse(
        status="verified",
        message="Email changed successfully. Sign in again to continue.",
    )


@router.post("/password-reset/request", response_model=NeutralActionResponse)
async def request_password_reset(
    request: Request,
    payload: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email
    await enforce_rate_limits(request, _password_reset_request_limit_policies(request, normalized_email))
    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.email == normalized_email)
    )
    user = result.scalar_one_or_none()
    response = NeutralActionResponse(message="If the account is eligible, a password reset email will be sent shortly.")

    await write_audit_log(
        db,
        action="password_reset_requested",
        actor_user=user,
        target_type="user" if user else None,
        target_id=user.id if user else None,
        after={"masked_email": mask_email(normalized_email)},
        request=request,
        success=True,
    )

    if user is None:
        await db.commit()
        return response

    reset_result = await issue_password_reset_token(db, user=user, request=request)
    await write_audit_log(
        db,
        action="password_reset_token_issued",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        after={
            "token_id": reset_result.token_id,
            "masked_email": mask_email(user.email),
            "expires_at": reset_result.expires_at.isoformat(),
            "invalidated_prior_tokens": reset_result.invalidated_count,
        },
        request=request,
        success=True,
    )
    await db.commit()
    try:
        await send_password_reset_email(to_email=user.email, secret=reset_result.raw_secret)
    except Exception:
        await write_audit_log(
            db,
            action="password_reset_delivery_failed",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"masked_email": mask_email(user.email)},
            request=request,
            success=False,
        )
        await db.commit()
    return response


@router.post("/password-reset/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_password_reset_route(
    request: Request,
    payload: AdminPasswordResetCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _password_reset_complete_limit_policies(request, payload.token))
    public_reset_token = await get_password_reset_token_by_secret(db, payload.token)
    if public_reset_token is not None:
        user_result = await db.execute(
            select(User)
            .options(selectinload(User.staff_permission))
            .where(User.id == public_reset_token.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token")

        previous_must_change_password = bool(user.must_change_password)
        try:
            await consume_password_reset_token(db, public_reset_token)
        except HTTPException:
            await write_audit_log(
                db,
                action="password_reset_complete_denied",
                actor_user=None,
                after={"token_id": public_reset_token.id, "reason": "token_inactive"},
                request=request,
                success=False,
            )
            await db.commit()
            raise

        invalidated_public_reset_count, invalidated_admin_reset_count, revoked_sessions = await complete_password_reset(
            db,
            user=user,
            token=public_reset_token,
            new_password_hash=get_password_hash(payload.new_password),
        )
        await write_audit_log(
            db,
            action="password_reset_completed",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            before={"must_change_password": previous_must_change_password},
            after={
                "must_change_password": False,
                "reset_token_id": public_reset_token.id,
                "invalidated_public_reset_tokens": invalidated_public_reset_count,
                "invalidated_admin_reset_tokens": invalidated_admin_reset_count,
                "revoked_session_count": revoked_sessions,
            },
            request=request,
            success=True,
        )
        await db.commit()
        return None

    reset_token = await get_admin_password_reset_token_by_secret(db, payload.token)
    if reset_token is None:
        await write_audit_log(
            db,
            action="password_reset_complete_denied",
            actor_user=None,
            after={"reason": "token_not_found"},
            request=request,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token")

    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == reset_token.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token")

    try:
        await consume_admin_password_reset_token(db, reset_token)
    except HTTPException:
        await write_audit_log(
            db,
            action="password_reset_complete_denied",
            actor_user=None,
            after={"token_id": reset_token.id, "reason": "admin_token_inactive"},
            request=request,
            success=False,
        )
        await db.commit()
        raise

    user.password_hash = get_password_hash(payload.new_password)
    user.must_change_password = False
    invalidated_public_reset_count, invalidated_admin_reset_count = await revoke_all_password_reset_tokens_for_user(
        db,
        user.id,
    )
    revoked_sessions = await revoke_all_refresh_tokens_for_user(db, user.id)

    await write_audit_log(
        db,
        action="password_reset_completed",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        before={"must_change_password": True},
        after={
            "must_change_password": False,
            "reset_token_id": reset_token.id,
            "invalidated_public_reset_tokens": invalidated_public_reset_count,
            "invalidated_admin_reset_tokens": invalidated_admin_reset_count,
            "revoked_session_count": revoked_sessions,
            "source": "admin_forced_reset",
        },
        request=request,
        success=True,
    )
    await db.commit()


@router.get("/me", response_model=UserRead)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current authenticated user information.
    
    Requires valid JWT token in Authorization header.
    """
    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter), selectinload(User.staff_permission))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return _build_user_read_response(user)
