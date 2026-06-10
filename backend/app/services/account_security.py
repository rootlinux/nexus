from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac as hmac_module
import secrets

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.datetime_utils import ensure_utc_datetime, to_naive_utc_datetime
from app.models.email_change_token import EmailChangeToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.admin_security import (
    revoke_active_admin_password_reset_tokens_for_user,
    revoke_all_refresh_tokens_for_user,
)
from app.services.mail import (
    build_email_change_message,
    build_email_verification_message,
    build_password_reset_message,
    get_mail_sender,
)


EMAIL_VERIFICATION_PURPOSE = "verify-email"
PASSWORD_RESET_PURPOSE = "password-reset"
EMAIL_CHANGE_PURPOSE = "email-change"


@dataclass(frozen=True)
class AccountSecurityIssueResult:
    raw_secret: str
    token_id: int
    expires_at: datetime
    invalidated_count: int


@dataclass(frozen=True)
class SessionRevocationResult:
    revoked_count: int
    revoked_session_ids: list[int]


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local_part, domain = email.split("@", 1)
    if len(local_part) <= 2:
        masked_local = local_part[:1] + "*"
    else:
        masked_local = local_part[:1] + ("*" * (len(local_part) - 2)) + local_part[-1:]
    return f"{masked_local}@{domain}"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_login_identifier(identifier: str) -> str:
    normalized = identifier.strip()
    if "@" in normalized:
        return normalize_email(normalized)
    return normalized


def hash_account_secret(secret: str) -> str:
    return hmac_module.new(
        settings.SECRET_KEY.encode("utf-8"),
        secret.encode("utf-8"),
        "sha256",
    ).hexdigest()


def generate_account_secret() -> str:
    return secrets.token_urlsafe(32)


def sanitize_user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    user_agent = request.headers.get("user-agent", "").strip()
    if not user_agent:
        return None
    return user_agent[:255]


def describe_client_device(request: Request | None) -> str | None:
    user_agent = sanitize_user_agent(request)
    if not user_agent:
        return None

    normalized = user_agent.lower()

    if "iphone" in normalized:
        platform = "iPhone"
    elif "ipad" in normalized:
        platform = "iPad"
    elif "android" in normalized:
        platform = "Android"
    elif "mac os x" in normalized or "macintosh" in normalized:
        platform = "macOS"
    elif "windows" in normalized:
        platform = "Windows"
    elif "linux" in normalized:
        platform = "Linux"
    else:
        platform = "Unknown device"

    if "edg/" in normalized:
        browser = "Edge"
    elif "chrome/" in normalized and "edg/" not in normalized:
        browser = "Chrome"
    elif "firefox/" in normalized:
        browser = "Firefox"
    elif "safari/" in normalized and "chrome/" not in normalized:
        browser = "Safari"
    else:
        browser = "Browser"

    return f"{browser} on {platform}"


def get_request_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def _revoke_active_tokens_for_user(
    db: AsyncSession,
    *,
    model,
    user_id: int,
) -> int:
    result = await db.execute(
        select(model).where(
            model.user_id == user_id,
            model.used_at.is_(None),
            model.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    count = 0
    for token in result.scalars().all():
        token.revoked_at = now
        count += 1
    return count


async def revoke_active_email_verification_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    return await _revoke_active_tokens_for_user(db, model=EmailVerificationToken, user_id=user_id)


async def revoke_active_password_reset_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    return await _revoke_active_tokens_for_user(db, model=PasswordResetToken, user_id=user_id)


async def revoke_active_email_change_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    return await _revoke_active_tokens_for_user(db, model=EmailChangeToken, user_id=user_id)


async def revoke_all_password_reset_tokens_for_user(db: AsyncSession, user_id: int) -> tuple[int, int]:
    public_count = await revoke_active_password_reset_tokens_for_user(db, user_id)
    admin_count = await revoke_active_admin_password_reset_tokens_for_user(db, user_id)
    return public_count, admin_count


async def _issue_token(
    db: AsyncSession,
    *,
    model,
    user: User,
    ttl_minutes: int,
    request: Request | None,
) -> AccountSecurityIssueResult:
    if model is EmailVerificationToken:
        invalidated_count = await revoke_active_email_verification_tokens_for_user(db, user.id)
    else:
        invalidated_count = await revoke_active_password_reset_tokens_for_user(db, user.id)

    raw_secret = generate_account_secret()
    token = model(
        user_id=user.id,
        email=user.email,
        token_hash=hash_account_secret(raw_secret),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        requested_by_ip=get_request_ip(request),
        requested_user_agent=sanitize_user_agent(request),
    )
    db.add(token)
    await db.flush()
    return AccountSecurityIssueResult(
        raw_secret=raw_secret,
        token_id=token.id,
        expires_at=token.expires_at,
        invalidated_count=invalidated_count,
    )


async def issue_email_verification_token(
    db: AsyncSession,
    *,
    user: User,
    request: Request | None,
) -> AccountSecurityIssueResult:
    return await _issue_token(
        db,
        model=EmailVerificationToken,
        user=user,
        ttl_minutes=settings.EMAIL_VERIFICATION_TOKEN_TTL_MINUTES,
        request=request,
    )


async def issue_password_reset_token(
    db: AsyncSession,
    *,
    user: User,
    request: Request | None,
) -> AccountSecurityIssueResult:
    return await _issue_token(
        db,
        model=PasswordResetToken,
        user=user,
        ttl_minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES,
        request=request,
    )


async def issue_email_change_token(
    db: AsyncSession,
    *,
    user: User,
    new_email: str,
    request: Request | None,
) -> AccountSecurityIssueResult:
    invalidated_count = await revoke_active_email_change_tokens_for_user(db, user.id)
    raw_secret = generate_account_secret()
    token = EmailChangeToken(
        user_id=user.id,
        pending_email=new_email,
        token_hash=hash_account_secret(raw_secret),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.EMAIL_VERIFICATION_TOKEN_TTL_MINUTES),
        requested_by_ip=get_request_ip(request),
        requested_user_agent=sanitize_user_agent(request),
    )
    db.add(token)
    await db.flush()
    return AccountSecurityIssueResult(
        raw_secret=raw_secret,
        token_id=token.id,
        expires_at=token.expires_at,
        invalidated_count=invalidated_count,
    )


async def get_email_verification_token_by_secret(
    db: AsyncSession,
    secret: str,
) -> EmailVerificationToken | None:
    result = await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_account_secret(secret))
    )
    return result.scalar_one_or_none()


async def get_password_reset_token_by_secret(
    db: AsyncSession,
    secret: str,
) -> PasswordResetToken | None:
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_account_secret(secret))
    )
    return result.scalar_one_or_none()


async def get_email_change_token_by_secret(
    db: AsyncSession,
    secret: str,
) -> EmailChangeToken | None:
    result = await db.execute(
        select(EmailChangeToken).where(EmailChangeToken.token_hash == hash_account_secret(secret))
    )
    return result.scalar_one_or_none()


def is_token_active(token) -> bool:
    expires_at = ensure_utc_datetime(token.expires_at) if token is not None else None
    return (
        token is not None
        and token.used_at is None
        and token.revoked_at is None
        and expires_at is not None
        and expires_at >= datetime.now(timezone.utc)
    )


async def _consume_one_time_token(
    db: AsyncSession,
    *,
    model,
    token,
    error_detail: str,
) -> datetime:
    consumed_at = datetime.now(timezone.utc)
    expires_at = ensure_utc_datetime(token.expires_at)
    if expires_at is None or expires_at < consumed_at:
        raise HTTPException(status_code=400, detail=error_detail)
    result = await db.execute(
        update(model)
        .where(
            model.id == token.id,
            model.used_at.is_(None),
            model.revoked_at.is_(None),
            model.expires_at >= consumed_at,
        )
        .values(used_at=consumed_at)
        .returning(model.id)
    )
    if result.scalar() is None:
        raise HTTPException(status_code=400, detail=error_detail)
    token.used_at = consumed_at
    return consumed_at


async def consume_email_verification_token(
    db: AsyncSession,
    token: EmailVerificationToken,
) -> datetime:
    return await _consume_one_time_token(
        db,
        model=EmailVerificationToken,
        token=token,
        error_detail="Invalid or expired verification link",
    )


async def consume_password_reset_token(
    db: AsyncSession,
    token: PasswordResetToken,
) -> datetime:
    return await _consume_one_time_token(
        db,
        model=PasswordResetToken,
        token=token,
        error_detail="Invalid or expired password reset token",
    )


async def consume_email_change_token(
    db: AsyncSession,
    token: EmailChangeToken,
) -> datetime:
    return await _consume_one_time_token(
        db,
        model=EmailChangeToken,
        token=token,
        error_detail="Invalid or expired email change token",
    )


def build_verification_url(secret: str) -> str:
    base = settings.WEB_BASE_URL.rstrip("/")
    return f"{base}/auth/verify-email?token={secret}"


def build_password_reset_url(secret: str) -> str:
    base = settings.WEB_BASE_URL.rstrip("/")
    return f"{base}/auth/reset-password?token={secret}"


def build_email_change_url(secret: str) -> str:
    base = settings.WEB_BASE_URL.rstrip("/")
    return f"{base}/auth/email-change?token={secret}"


async def send_verification_email(*, to_email: str, secret: str) -> None:
    sender = get_mail_sender()
    await sender.send(
        build_email_verification_message(
            to_email=to_email,
            verification_url=build_verification_url(secret),
        )
    )


async def send_password_reset_email(*, to_email: str, secret: str) -> None:
    sender = get_mail_sender()
    await sender.send(
        build_password_reset_message(
            to_email=to_email,
            reset_url=build_password_reset_url(secret),
        )
    )


async def send_email_change_email(*, to_email: str, secret: str) -> None:
    sender = get_mail_sender()
    await sender.send(
        build_email_change_message(
            to_email=to_email,
            verification_url=build_email_change_url(secret),
        )
    )


async def mark_email_verified(db: AsyncSession, *, user: User, token: EmailVerificationToken) -> int:
    now = ensure_utc_datetime(token.used_at) or datetime.now(timezone.utc)
    if user.email_verified_at is None:
        user.email_verified_at = to_naive_utc_datetime(now)
    return await revoke_active_email_verification_tokens_for_user(db, user.id)


async def complete_password_reset(
    db: AsyncSession,
    *,
    user: User,
    token: PasswordResetToken,
    new_password_hash: str,
) -> tuple[int, int, int]:
    user.password_hash = new_password_hash
    user.must_change_password = False
    invalidated_public_reset_count, invalidated_admin_reset_count = await revoke_all_password_reset_tokens_for_user(
        db,
        user.id,
    )
    revoked_session_count = await revoke_all_refresh_tokens_for_user(db, user.id)
    return invalidated_public_reset_count, invalidated_admin_reset_count, revoked_session_count


async def list_active_sessions_for_user(db: AsyncSession, user_id: int) -> list[RefreshToken]:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        )
    )
    sessions = list(result.scalars().all())
    sessions.sort(key=lambda session: session.created_at or datetime.min, reverse=True)
    return sessions


async def revoke_refresh_tokens_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    exclude_session_ids: set[int] | None = None,
) -> SessionRevocationResult:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        )
    )
    revoked_session_ids: list[int] = []
    excluded = exclude_session_ids or set()
    for token in result.scalars().all():
        if token.id in excluded:
            continue
        token.revoked = True
        revoked_session_ids.append(token.id)
    return SessionRevocationResult(
        revoked_count=len(revoked_session_ids),
        revoked_session_ids=revoked_session_ids,
    )
