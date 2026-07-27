"""Shared, non-collected test helpers for Round 2 Task 3's media-ownership
tests. Not a test module itself (no test_ prefix)."""
import secrets
from datetime import datetime

import bcrypt

import app.models.webauthn_credential  # noqa: F401 — registers the mapper User.webauthn_credentials resolves by string name
from app.models.user import User, UserStatus


async def create_test_user(session, *, username: str | None = None) -> User:
    user = User(
        username=username or f"media-test-{secrets.token_hex(4)}",
        email=f"media-test-{secrets.token_hex(4)}@example.com",
        password_hash=bcrypt.hashpw(b"irrelevant", bcrypt.gensalt()).decode(),
        status=UserStatus.ACTIVE,
        is_active=True,
        email_verified_at=datetime.utcnow(),
    )
    session.add(user)
    await session.flush()
    return user
