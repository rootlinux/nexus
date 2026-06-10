from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import jwt
from jwt import PyJWTError as JWTError
from app.core.authorization import user_has_capability
from app.core.config import settings
from app.core.database import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.schemas.auth import TokenData
from app.services.account_security import mask_email

# Security scheme
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def enforce_not_banned(user: User) -> User:
    if user.status == UserStatus.BANNED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been banned. Contact support for more information."
        )

    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended. Contact support for more information."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not permitted to access this resource."
        )

    return user


def enforce_email_verified(user: User) -> User:
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "EMAIL_VERIFICATION_REQUIRED",
                "message": "Verify your email before continuing.",
                "masked_email": mask_email(user.email),
            },
        )
    return user


def enforce_can_interact(user: User) -> User:
    if user.status == UserStatus.BANNED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been banned. Contact support for more information."
        )
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended. Contact support for more information."
        )
    if user.status == UserStatus.FROZEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is frozen. Posting and interactions are temporarily disabled."
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not permitted to access this resource."
        )
    return user


def _decode_access_token(token: str) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub"]}
        )
        user_id_raw = payload.get("sub")
        username = payload.get("username")
        session_id_raw = payload.get("sid")

        if user_id_raw is None:
            raise credentials_exception

        return TokenData(
            user_id=int(user_id_raw),
            username=username,
            session_id=int(session_id_raw) if session_id_raw is not None else None,
        )
    except (JWTError, ValueError):
        raise credentials_exception


async def _resolve_active_session(db: AsyncSession, token_data: TokenData) -> RefreshToken | None:
    session_id = getattr(token_data, "session_id", None)
    if session_id is None:
        return None

    result = await db.execute(select(RefreshToken).where(RefreshToken.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if session.user_id != token_data.user_id or session.revoked or session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Authorization credentials (Bearer token)
        db: Database session
        
    Returns:
        User object
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    token_data = _decode_access_token(credentials.credentials)
    
    # Query user from database
    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    active_session = await _resolve_active_session(db, token_data)
    user = enforce_not_banned(user)
    user = enforce_email_verified(user)
    setattr(user, "_current_session_id", active_session.id if active_session is not None else None)
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    if credentials is None:
        return None

    token_data = _decode_access_token(credentials.credentials)

    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    active_session = await _resolve_active_session(db, token_data)
    user = enforce_not_banned(user)
    user = enforce_email_verified(user)
    setattr(user, "_current_session_id", active_session.id if active_session is not None else None)
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency to get the current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


require_auth = get_current_user


async def get_current_interactive_user(
    current_user: User = Depends(get_current_user)
) -> User:
    return enforce_can_interact(current_user)


async def require_admin_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get the current staff user for admin-sensitive routes.

    Authorization is resolved from the DB-backed staff_permissions record.
    """
    token_data = _decode_access_token(credentials.credentials)
    
    # Query user from database
    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    active_session = await _resolve_active_session(db, token_data)
    if active_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = enforce_not_banned(user)
    setattr(user, "_current_session_id", active_session.id)

    if user.staff_permission is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin session required"
        )

    credential_result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .limit(1)
    )
    has_webauthn = credential_result.scalar_one_or_none() is not None
    if has_webauthn and not active_session.mfa_satisfied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin session requires MFA authentication",
        )

    return user


get_current_admin_user = require_admin_session


def require_capability(capability: str):
    async def dependency(
        current_admin: User = Depends(require_admin_session),
    ) -> User:
        if not user_has_capability(current_admin, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action"
            )
        return current_admin

    return dependency
