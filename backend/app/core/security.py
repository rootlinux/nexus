from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
import jwt
from jwt import PyJWTError as JWTError
import bcrypt
import hashlib
import hmac
import secrets
from app.core.config import settings

_MFA_PENDING_PREFIX = "mfa_pending:"
_ADMIN_WEBAUTHN_RECOVERY_PENDING_PREFIX = "admin_webauthn_recovery:"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12)
    ).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Dictionary containing the payload data (e.g., user_id, username)
        expires_delta: Optional custom expiration time
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt


def create_refresh_token() -> str:
    """
    Create a secure random refresh token.
    
    Returns:
        A secure random hex string (64 characters)
    """
    return secrets.token_hex(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_refresh_token(token: str, stored_hash: str) -> bool:
    """
    Verify a refresh token against its stored hash.

    Args:
        token: The raw refresh token
        stored_hash: The stored SHA256 hash

    Returns:
        True if the token matches the hash
    """
    return hmac.compare_digest(hash_refresh_token(token), stored_hash)


async def _set_mfa_pending_state(jti: str, user_id: int, ttl_seconds: int) -> None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    await redis.setex(f"{_MFA_PENDING_PREFIX}{jti}", ttl_seconds, str(user_id))


async def _set_admin_webauthn_recovery_pending_state(jti: str, user_id: int, ttl_seconds: int) -> None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    await redis.setex(f"{_ADMIN_WEBAUTHN_RECOVERY_PENDING_PREFIX}{jti}", ttl_seconds, str(user_id))


async def get_mfa_pending_user_id(jti: str) -> int | None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    raw = await redis.get(f"{_MFA_PENDING_PREFIX}{jti}")
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def consume_mfa_pending_user_id(jti: str) -> int | None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    raw = await redis.getdel(f"{_MFA_PENDING_PREFIX}{jti}")
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def get_admin_webauthn_recovery_user_id(jti: str) -> int | None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    raw = await redis.get(f"{_ADMIN_WEBAUTHN_RECOVERY_PENDING_PREFIX}{jti}")
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def consume_admin_webauthn_recovery_user_id(jti: str) -> int | None:
    from app.core.rate_limit import get_redis_client

    redis = await get_redis_client()
    raw = await redis.getdel(f"{_ADMIN_WEBAUTHN_RECOVERY_PENDING_PREFIX}{jti}")
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def create_mfa_session_token(
    user_id: int,
    ttl_minutes: int = settings.WEBAUTHN_MFA_TOKEN_TTL_MINUTES,
) -> str:
    """Create a short-lived JWT used as an MFA session token.

    The token identifies the user after a successful password check but before
    the WebAuthn assertion is verified.  It must not be accepted as a full
    session credential anywhere else.
    """
    jti = uuid4().hex
    expire = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    ttl_seconds = max(1, int(timedelta(minutes=ttl_minutes).total_seconds()))
    await _set_mfa_pending_state(jti, user_id, ttl_seconds)
    return jwt.encode(
        {"sub": str(user_id), "purpose": "webauthn_mfa", "jti": jti, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_mfa_session_token(token: str) -> dict[str, int | str]:
    """Decode a MFA session token and return the user_id plus jti.

    Raises ValueError on any invalid token so callers can convert to HTTPException.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired MFA session token") from exc
    if payload.get("purpose") != "webauthn_mfa":
        raise ValueError("Invalid MFA session token purpose")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Invalid MFA session token subject") from exc
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise ValueError("Invalid MFA session token identifier")
    return {"user_id": user_id, "jti": jti}


async def create_admin_webauthn_recovery_token(
    user_id: int,
    ttl_minutes: int = settings.ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES,
) -> str:
    jti = uuid4().hex
    expire = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    ttl_seconds = max(1, int(timedelta(minutes=ttl_minutes).total_seconds()))
    await _set_admin_webauthn_recovery_pending_state(jti, user_id, ttl_seconds)
    return jwt.encode(
        {"sub": str(user_id), "purpose": "admin_webauthn_recovery", "jti": jti, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_admin_webauthn_recovery_token(token: str) -> dict[str, int | str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired admin WebAuthn recovery token") from exc
    if payload.get("purpose") != "admin_webauthn_recovery":
        raise ValueError("Invalid admin WebAuthn recovery token purpose")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Invalid admin WebAuthn recovery token subject") from exc
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise ValueError("Invalid admin WebAuthn recovery token identifier")
    return {"user_id": user_id, "jti": jti}
