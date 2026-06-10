from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_password_reset_token import AdminPasswordResetToken
from app.models.refresh_token import RefreshToken

ADMIN_PASSWORD_RESET_TOKEN_TTL_MINUTES = 30


def generate_admin_password_reset_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_admin_password_reset_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def revoke_active_admin_password_reset_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(AdminPasswordResetToken).where(
            AdminPasswordResetToken.user_id == user_id,
            AdminPasswordResetToken.used_at.is_(None),
            AdminPasswordResetToken.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    count = 0
    for token in result.scalars().all():
        token.revoked_at = now
        count += 1
    return count


async def issue_admin_password_reset_token(
    db: AsyncSession,
    *,
    user_id: int,
    issued_by_user_id: int,
    ttl_minutes: int = ADMIN_PASSWORD_RESET_TOKEN_TTL_MINUTES,
) -> tuple[AdminPasswordResetToken, str, int]:
    revoked_count = await revoke_active_admin_password_reset_tokens_for_user(db, user_id)
    raw_secret = generate_admin_password_reset_secret()
    token = AdminPasswordResetToken(
        user_id=user_id,
        token_hash=hash_admin_password_reset_secret(raw_secret),
        issued_by_user_id=issued_by_user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    db.add(token)
    await db.flush()
    return token, raw_secret, revoked_count


async def get_admin_password_reset_token_by_secret(
    db: AsyncSession,
    secret: str,
) -> AdminPasswordResetToken | None:
    token_hash = hash_admin_password_reset_secret(secret)
    result = await db.execute(
        select(AdminPasswordResetToken).where(AdminPasswordResetToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def consume_admin_password_reset_token(
    db: AsyncSession,
    token: AdminPasswordResetToken,
) -> datetime:
    consumed_at = datetime.now(timezone.utc)
    result = await db.execute(
        update(AdminPasswordResetToken)
        .where(
            AdminPasswordResetToken.id == token.id,
            AdminPasswordResetToken.used_at.is_(None),
            AdminPasswordResetToken.revoked_at.is_(None),
            AdminPasswordResetToken.expires_at >= consumed_at,
        )
        .values(used_at=consumed_at)
        .returning(AdminPasswordResetToken.id)
    )
    if result.scalar() is None:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token")
    token.used_at = consumed_at
    return consumed_at


async def revoke_all_refresh_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        )
    )
    count = 0
    for token in result.scalars().all():
        token.revoked = True
        count += 1
    return count


async def count_active_refresh_tokens_for_user(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        )
    )
    return len(result.scalars().all())
