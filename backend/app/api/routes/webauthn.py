"""
FIDO2/WebAuthn router.

Endpoints
---------
POST /webauthn/register/begin    – generate registration options (auth required)
POST /webauthn/register/complete – verify attestation + persist credential (auth required)
POST /webauthn/auth/begin        – generate authentication options (mfa_session_token)
POST /webauthn/auth/complete     – verify assertion + issue full JWT (mfa_session_token)
GET  /webauthn/credentials       – list the current user's registered keys (auth required)
DELETE /webauthn/credentials/{id} – remove a key (auth required)
"""

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import parse_authentication_credential_json, parse_registration_credential_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, get_redis_client, hash_key_part
from app.core.security import (
    consume_admin_webauthn_recovery_user_id,
    consume_mfa_pending_user_id,
    create_access_token,
    create_refresh_token,
    decode_admin_webauthn_recovery_token,
    decode_mfa_session_token,
    get_admin_webauthn_recovery_user_id,
    get_mfa_pending_user_id,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.schemas.webauthn import (
    WebAuthnAuthBeginRequest,
    WebAuthnAuthBeginResponse,
    WebAuthnAuthCompleteRequest,
    WebAuthnCredentialDeleteRequest,
    WebAuthnCredentialRead,
    WebAuthnRecoveryRegisterBeginRequest,
    WebAuthnRecoveryRegisterCompleteRequest,
    WebAuthnRegisterBeginRequest,
    WebAuthnRegisterBeginResponse,
    WebAuthnRegisterCompleteRequest,
)
from app.services.admin_security import revoke_all_refresh_tokens_for_user
from app.services.account_security import describe_client_device
from app.services.audit import write_audit_log
from app.services.staff_permissions import staff_session_requires_security_key

router = APIRouter(tags=["webauthn"])

_REDIS_REG_PREFIX = "webauthn:reg_challenge:"
_REDIS_AUTH_PREFIX = "webauthn:auth_challenge:"
_CHALLENGE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64encode_challenge(challenge: bytes) -> str:
    return base64.urlsafe_b64encode(challenge).decode().rstrip("=")


def _b64decode_challenge(value: str) -> bytes:
    # Restore padding stripped during encoding
    padding = 4 - len(value) % 4
    if padding != 4:
        value += "=" * padding
    return base64.urlsafe_b64decode(value)


def _decode_base64url_bytes(value: str) -> bytes:
    padding = 4 - len(value) % 4
    if padding != 4:
        value += "=" * padding
    return base64.urlsafe_b64decode(value)


def _require_mfa_token(token: str) -> dict[str, int | str]:
    """Decode MFA session token, raising HTTP 401 on failure."""
    try:
        return decode_mfa_session_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


def _require_admin_recovery_token(token: str) -> dict[str, int | str]:
    try:
        return decode_admin_webauthn_recovery_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


async def _set_redis_challenge(prefix: str, key: str, challenge: bytes) -> None:
    redis = await get_redis_client()
    await redis.setex(f"{prefix}{key}", _CHALLENGE_TTL, _b64encode_challenge(challenge))


async def _consume_redis_challenge(prefix: str, key: str) -> bytes | None:
    redis = await get_redis_client()
    raw = await redis.getdel(f"{prefix}{key}")
    if raw is None:
        return None
    return _b64decode_challenge(raw.decode() if isinstance(raw, bytes) else raw)


def _webauthn_register_policies(user_id: int, action: str) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name=f"webauthn-register-{action}",
            limit=5,
            window_seconds=60,
            key=build_scope_key("webauthn", "register", action, "user", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _webauthn_auth_policies(request: Request, user_id: int, action: str) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name=f"webauthn-auth-{action}-ip",
            limit=10,
            window_seconds=60,
            key=build_scope_key("webauthn", "auth", action, "ip", hash_key_part(get_client_ip(request))),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name=f"webauthn-auth-{action}-user",
            limit=5,
            window_seconds=60,
            key=build_scope_key("webauthn", "auth", action, "user", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _configured_admin_recovery_identifier() -> str | None:
    raw_identifier = settings.ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER
    if raw_identifier is None:
        return None
    identifier = raw_identifier.strip().lower()
    return identifier or None


async def _load_recovery_eligible_admin(db: AsyncSession, user_id: int) -> User:
    if not settings.ENABLE_ADMIN_WEBAUTHN_RECOVERY or _configured_admin_recovery_identifier() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )

    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )
    if not staff_session_requires_security_key(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )
    if user.email_verified_at is None or user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )
    if not user.is_active or user.status in {UserStatus.BANNED, UserStatus.SUSPENDED}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )

    existing_result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .limit(1)
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin WebAuthn recovery is not available for this account.",
        )
    return user


# ---------------------------------------------------------------------------
# Registration endpoints (authenticated user)
# ---------------------------------------------------------------------------


@router.post("/register/begin", response_model=WebAuthnRegisterBeginResponse)
async def webauthn_register_begin(
    request: Request,
    body: WebAuthnRegisterBeginRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate WebAuthn registration options and cache the challenge."""
    await enforce_rate_limits(request, _webauthn_register_policies(current_user.id, "begin"))
    if not body.current_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password required to add a security key",
        )
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )

    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(current_user.id).encode(),
        user_name=current_user.username,
        user_display_name=current_user.display_name or current_user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    await _set_redis_challenge(_REDIS_REG_PREFIX, str(current_user.id), options.challenge)

    return WebAuthnRegisterBeginResponse(options=json.loads(options_to_json(options)))


@router.post("/recovery/register/begin", response_model=WebAuthnRegisterBeginResponse)
async def webauthn_recovery_register_begin(
    request: Request,
    body: WebAuthnRecoveryRegisterBeginRequest,
    db: AsyncSession = Depends(get_db),
):
    token_payload = _require_admin_recovery_token(body.recovery_token)
    user_id = int(token_payload["user_id"])
    jti = str(token_payload["jti"])
    await enforce_rate_limits(request, _webauthn_register_policies(user_id, "recovery-begin"))
    pending_user_id = await get_admin_webauthn_recovery_user_id(jti)
    if pending_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin WebAuthn recovery session expired or already used",
        )

    user = await _load_recovery_eligible_admin(db, user_id)
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.username,
        user_display_name=user.display_name or user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    await _set_redis_challenge(_REDIS_REG_PREFIX, str(user.id), options.challenge)
    return WebAuthnRegisterBeginResponse(options=json.loads(options_to_json(options)))


@router.post("/register/complete", response_model=WebAuthnCredentialRead)
async def webauthn_register_complete(
    body: WebAuthnRegisterCompleteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify attestation response and persist the new credential."""
    await enforce_rate_limits(request, _webauthn_register_policies(current_user.id, "complete"))
    challenge = await _consume_redis_challenge(_REDIS_REG_PREFIX, str(current_user.id))
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration challenge not found or expired. Please start over.",
        )

    try:
        credential = parse_registration_credential_json(json.dumps(body.credential))
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security key verification failed: {exc}",
        )

    existing_result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == verification.credential_id,
        )
    )
    existing_credential = existing_result.scalar_one_or_none()
    if existing_credential is not None:
        detail = "This security key is already registered"
        if existing_credential.user_id == current_user.id:
            detail = "This security key is already registered to your account"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # Persist the credential
    db_cred = WebAuthnCredential(
        user_id=current_user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=body.name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(db_cred)

    try:
        await write_audit_log(
            db,
            action="webauthn.key_registered",
            actor_user=current_user,
            target_type="user",
            target_id=current_user.id,
            after={"key_name": body.name},
            request=request,
            success=True,
        )

        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This security key is already registered",
        ) from exc
    await db.refresh(db_cred)

    return WebAuthnCredentialRead.model_validate(db_cred)


@router.post("/recovery/register/complete", response_model=WebAuthnCredentialRead)
async def webauthn_recovery_register_complete(
    body: WebAuthnRecoveryRegisterCompleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token_payload = _require_admin_recovery_token(body.recovery_token)
    user_id = int(token_payload["user_id"])
    jti = str(token_payload["jti"])
    await enforce_rate_limits(request, _webauthn_register_policies(user_id, "recovery-complete"))
    challenge = await _consume_redis_challenge(_REDIS_REG_PREFIX, str(user_id))
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration challenge not found or expired. Please start over.",
        )

    user = await _load_recovery_eligible_admin(db, user_id)
    try:
        credential = parse_registration_credential_json(json.dumps(body.credential))
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security key verification failed: {exc}",
        )

    existing_result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == verification.credential_id,
        )
    )
    existing_credential = existing_result.scalar_one_or_none()
    if existing_credential is not None:
        detail = "This security key is already registered"
        if existing_credential.user_id == user.id:
            detail = "This security key is already registered to your account"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    pending_user_id = await consume_admin_webauthn_recovery_user_id(jti)
    if pending_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin WebAuthn recovery session expired or already used",
        )

    db_cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=body.name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(db_cred)
    await db.flush()

    try:
        await write_audit_log(
            db,
            action="webauthn.recovery_key_registered",
            actor_user=user,
            target_type="user",
            target_id=user.id,
            after={"key_name": body.name},
            request=request,
            success=True,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This security key is already registered",
        ) from exc
    await db.refresh(db_cred)
    return WebAuthnCredentialRead.model_validate(db_cred)


# ---------------------------------------------------------------------------
# Authentication endpoints (MFA session token, no full auth required)
# ---------------------------------------------------------------------------


@router.post("/auth/begin", response_model=WebAuthnAuthBeginResponse)
async def webauthn_auth_begin(
    request: Request,
    body: WebAuthnAuthBeginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate authentication options for a user identified by mfa_session_token.
    Called immediately after a successful password check when mfa_required=true.
    """
    token_payload = _require_mfa_token(body.mfa_session_token)
    user_id = int(token_payload["user_id"])
    jti = str(token_payload["jti"])
    await enforce_rate_limits(request, _webauthn_auth_policies(request, user_id, "begin"))
    pending_user_id = await get_mfa_pending_user_id(jti)
    if pending_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA session expired or already used",
        )

    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
    )
    credentials = result.scalars().all()

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No security keys registered for this account",
        )

    allow_credentials = [
        PublicKeyCredentialDescriptor(id=cred.credential_id) for cred in credentials
    ]

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    await _set_redis_challenge(_REDIS_AUTH_PREFIX, str(user_id), options.challenge)

    return WebAuthnAuthBeginResponse(options=json.loads(options_to_json(options)))


@router.post("/auth/complete")
async def webauthn_auth_complete(
    body: WebAuthnAuthCompleteRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify assertion response and issue a full JWT + refresh token session.
    Returns a Token object (same shape as the normal /login response).
    """
    token_payload = _require_mfa_token(body.mfa_session_token)
    user_id = int(token_payload["user_id"])
    jti = str(token_payload["jti"])
    await enforce_rate_limits(request, _webauthn_auth_policies(request, user_id, "complete"))

    challenge = await _consume_redis_challenge(_REDIS_AUTH_PREFIX, str(user_id))
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication challenge not found or expired. Please start over.",
        )

    # Find the credential being used (raw_id in the response identifies it)
    raw_id_b64 = body.credential.get("rawId") or body.credential.get("id")
    if not raw_id_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing credential id in response",
        )

    # raw_id_b64 is a base64url string; convert to bytes for DB lookup
    credential_id_bytes = _decode_base64url_bytes(raw_id_b64)

    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user_id,
            WebAuthnCredential.credential_id == credential_id_bytes,
        )
    )
    db_cred = result.scalar_one_or_none()
    if db_cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security key not recognised",
        )

    try:
        auth_credential = parse_authentication_credential_json(json.dumps(body.credential))
        verification = verify_authentication_response(
            credential=auth_credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=db_cred.public_key,
            credential_current_sign_count=db_cred.sign_count,
        )
    except InvalidAuthenticationResponse as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Security key authentication failed: {exc}",
        )
    pending_user_id = await consume_mfa_pending_user_id(jti)
    if pending_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA session expired or already used",
        )

    # Update sign count and last_used_at
    db_cred.sign_count = verification.new_sign_count
    db_cred.last_used_at = datetime.now(timezone.utc)

    # Load user for token creation
    user_result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Issue session tokens
    raw_refresh = create_refresh_token()
    from datetime import timedelta as _td
    expires_at = datetime.now(timezone.utc) + _td(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    import hashlib as _hashlib

    _ua = request.headers.get("user-agent", "")
    _lang = request.headers.get("accept-language", "")
    _encoding = request.headers.get("accept-encoding", "")
    _platform = request.headers.get("sec-ch-ua-platform", "")
    _raw = f"{_ua}|{_lang}|{_encoding}|{_platform}"
    device_fp = _hashlib.sha256(_raw.encode()).hexdigest()[:32]
    device_label = describe_client_device(request)

    db_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=expires_at,
        mfa_satisfied=True,
        last_used_at=datetime.now(timezone.utc),
        device_label=device_label,
        device_fingerprint=device_fp,
    )
    db.add(db_token)
    await db.flush()

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "sid": str(db_token.id),
        }
    )

    await write_audit_log(
        db,
        action="login.webauthn_complete",
        actor_user=user,
        target_type="user",
        target_id=user.id,
        request=request,
        session_id=db_token.id,
        success=True,
    )

    await db.commit()

    prefers_cookie = (
        request.headers.get("x-session-transport", "").lower() == "cookie"
    )
    if prefers_cookie:
        response.set_cookie(
            key=settings.REFRESH_COOKIE_NAME,
            value=raw_refresh,
            httponly=True,
            secure=settings.refresh_cookie_secure,
            samesite=settings.REFRESH_COOKIE_SAMESITE,
            domain=settings.REFRESH_COOKIE_DOMAIN,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            expires=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            path="/api/auth",
        )
        return {"access_token": access_token, "refresh_token": None, "token_type": "bearer"}

    return {"access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Credential management (authenticated user)
# ---------------------------------------------------------------------------


@router.get("/credentials", response_model=list[WebAuthnCredentialRead])
async def list_webauthn_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all WebAuthn keys registered by the current user."""
    result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == current_user.id)
        .order_by(WebAuthnCredential.created_at)
    )
    return [WebAuthnCredentialRead.model_validate(c) for c in result.scalars().all()]


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webauthn_credential(
    credential_id: int,
    body: WebAuthnCredentialDeleteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a registered security key by its database id."""
    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.id == credential_id,
            WebAuthnCredential.user_id == current_user.id,
        )
    )
    db_cred = result.scalar_one_or_none()
    if db_cred is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Security key not found",
        )

    remaining_credentials_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == current_user.id)
    )
    remaining_credentials = remaining_credentials_result.scalars().all()
    deleting_last_credential = len(remaining_credentials) == 1

    if not body.current_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password required to remove security key",
        )
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )
    if deleting_last_credential and current_user.staff_permission is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Privileged accounts must retain at least one security key. "
                "Register a replacement key before removing this one."
            ),
        )

    await db.delete(db_cred)
    revoked_session_count = await revoke_all_refresh_tokens_for_user(db, current_user.id)

    await write_audit_log(
        db,
        action="webauthn.key_removed",
        actor_user=current_user,
        target_type="user",
        target_id=current_user.id,
        after={
            "credential_db_id": credential_id,
            "key_name": db_cred.name,
            "revoked_session_count": revoked_session_count,
        },
        request=request,
        success=True,
    )

    await db.commit()
