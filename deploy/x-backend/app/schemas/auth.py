from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.services.account_security import normalize_email
from app.schemas.user import UserRead
from app.schemas.user import _validate_password_strength


class Token(BaseModel):
    """Schema for JWT access token response."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserRead] = None


class AdminWebAuthnRecoveryTokenResponse(BaseModel):
    recovery_token: str
    expires_in_seconds: int


class TokenData(BaseModel):
    """Schema for decoded JWT token data."""
    user_id: Optional[int] = None
    username: Optional[str] = None
    session_id: Optional[int] = None


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request."""
    refresh_token: Optional[str] = Field(None, max_length=200)


class LogoutRequest(BaseModel):
    """Schema for logout request."""
    refresh_token: Optional[str] = Field(None, max_length=200)


class AdminPasswordResetCompleteRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_strength(v.strip())


class PendingEmailVerificationResponse(BaseModel):
    status: str = "pending_email_verification"
    message: str
    email: str
    masked_email: str


class NeutralActionResponse(BaseModel):
    message: str


class PasswordConfirmRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)


class EmailActionRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email_value(cls, v: str) -> str:
        return normalize_email(v)


class SessionRead(BaseModel):
    id: int
    is_current: bool
    created_at: str
    last_used_at: Optional[str] = None
    expires_at: str
    device_label: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionRead]


class SessionRevokeResponse(BaseModel):
    revoked_session_id: int


class OtherSessionsRevokeResponse(BaseModel):
    revoked_session_count: int


class EmailChangeRequest(BaseModel):
    new_email: str = Field(..., min_length=3, max_length=255)
    current_password: str = Field(..., min_length=1, max_length=128)

    @field_validator("new_email")
    @classmethod
    def normalize_new_email(cls, v: str) -> str:
        return normalize_email(v)


class EmailChangeCompleteRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=512)


class EmailTokenCompleteRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=512)


class EmailTokenCompletionResponse(BaseModel):
    status: str
    message: str
