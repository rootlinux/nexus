import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator, Field
from app.core.authorization import AdminRole
from app.models.user import UserStatus
from app.schemas.follow import UserProfile as FollowUserProfile
from app.services.account_security import normalize_email, normalize_login_identifier


def _validate_password_strength(password: str) -> str:
    """Enforce minimum password complexity requirements."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain at least one special character")
    return password


class InviterRead(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    """Base user schema with common fields."""
    username: str
    display_name: Optional[str] = None
    email: EmailStr


class UserCreate(BaseModel):
    """Schema for creating a new user."""
    username: str
    display_name: str  # User's display name
    email: EmailStr
    password: str
    invite_code: str  # Required invite code for registration
    request_key: str | None = None
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username: alphanumeric + underscore only, 3-20 chars."""
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', v):
            raise ValueError('Username must be alphanumeric (letters, numbers, underscore) only, 3-20 characters')
        return v
    
    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        """Validate display name: 1-50 chars, allows spaces and common characters."""
        if not v or len(v.strip()) < 1:
            raise ValueError('Display name is required')
        if len(v) > 50:
            raise ValueError('Display name must be 50 characters or less')
        return v.strip()

    @field_validator("email")
    @classmethod
    def normalize_email_value(cls, v: EmailStr) -> str:
        return normalize_email(str(v))

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)

    @field_validator('invite_code')
    @classmethod
    def validate_invite_code(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError('Invite code is required')
        return normalized


class UserLogin(BaseModel):
    """Schema for user login."""
    username: str = Field(..., max_length=100)  # Can be username or email
    password: str = Field(..., max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)


class UserRead(UserBase):
    """Schema for reading user data (response)."""
    id: int
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=160)
    location: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=255)
    created_at: datetime
    is_active: bool
    email_verified: bool = False
    email_verified_at: Optional[datetime] = None
    is_admin: bool
    admin_role: Optional[AdminRole] = None
    status: UserStatus = UserStatus.ACTIVE
    banned_at: Optional[datetime] = None
    ban_reason: Optional[str] = None
    status_reason: Optional[str] = None
    status_changed_at: Optional[datetime] = None
    status_changed_by_user_id: Optional[int] = None
    invited_by_user_id: Optional[int] = None
    invite_id_used: Optional[int] = None
    inviter: Optional[InviterRead] = None

    model_config = ConfigDict(from_attributes=True)


class UserPublicRead(BaseModel):
    """Public user shape safe for post/feed/detail payloads."""
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=160)
    location: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=255)
    created_at: datetime
    inviter: Optional[InviterRead] = None

    model_config = ConfigDict(from_attributes=True)


class UserReadWithModeration(UserRead):
    """Extended user schema with full moderation details for admin UI."""
    banned_by_user_id: Optional[int] = None
    invited_by_username: Optional[str] = None
    invited_users_count: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


class UserPublicProfile(FollowUserProfile):
    """Profile schema safe for standard public/profile reads.
    
    Does NOT include: is_admin, admin_role, banned_at, ban_reason, status_reason,
    status_changed_at, status_changed_by_user_id.
    """
    pass


class UserPrivateProfile(UserPublicProfile):
    """Profile schema for the owner or staff/admin sessions.
    
    Includes: is_admin, admin_role, status.
    Does NOT include moderation-specific fields (banned_at, ban_reason, status_reason)
    which are reserved for a separate admin-only schema.
    """
    is_admin: bool
    admin_role: Optional[AdminRole] = None
    status: UserStatus = UserStatus.ACTIVE


class UserAdminProfile(UserPrivateProfile):
    """Extended user schema with full moderation details for admin UI only."""
    banned_at: Optional[datetime] = None
    ban_reason: Optional[str] = None
    status_reason: Optional[str] = None
    status_changed_at: Optional[datetime] = None
    status_changed_by_user_id: Optional[int] = None


class UserModerationAction(BaseModel):
    """Schema for moderation actions (ban/unban/suspend)."""
    user_id: int
    reason: Optional[str] = None


class UserBanRequest(BaseModel):
    """Schema for banning a user."""
    reason: str = Field(..., min_length=3, max_length=500)


class UserUnbanRequest(BaseModel):
    """Schema for unbanning a user."""
    pass


class UserSuspendRequest(BaseModel):
    """Schema for suspending a user."""
    reason: str = Field(..., min_length=3, max_length=500)


class UserFreezeRequest(BaseModel):
    """Schema for freezing a user."""
    reason: str = Field(..., min_length=3, max_length=500)


class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=160)
    location: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=255)

    @field_validator("display_name")
    @classmethod
    def validate_optional_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        if not normalized:
            return None
        if len(normalized) > 50:
            raise ValueError("Display name must be 50 characters or less")
        return normalized

    @field_validator("bio")
    @classmethod
    def validate_optional_bio(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        return normalized or None

    @field_validator("location")
    @classmethod
    def validate_optional_location(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        if not normalized:
            return None
        if len(normalized) > 100:
            raise ValueError("Location must be 100 characters or less")
        return normalized

    @field_validator("website")
    @classmethod
    def validate_optional_website(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        if not normalized:
            return None
        candidate = normalized if "://" in normalized else f"https://{normalized}"
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Website must be a valid HTTP or HTTPS URL")
        return candidate


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_strength(v.strip())


class AvatarUploadResponse(BaseModel):
    avatar_url: str


class CoverUploadResponse(BaseModel):
    cover_url: str
