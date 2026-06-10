from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ==================== Request Schemas ====================

class InviteCreate(BaseModel):
    """Schema for creating a new admin invite code."""
    model_config = ConfigDict(extra="forbid")

    internal_note: Optional[str] = Field(None, max_length=255)
    assigned_to_username: Optional[str] = Field(None, min_length=1, max_length=50)
    expires_days: Optional[int] = Field(None, ge=1)  # days from now, calculated server-side

    @field_validator("internal_note")
    @classmethod
    def normalize_internal_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("assigned_to_username")
    @classmethod
    def normalize_assigned_to_username(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


# ==================== Response Schemas ====================

class InviteRead(BaseModel):
    """Schema for reading invite code data (response)."""
    id: int
    code: str
    created_by_id: int
    generated_by_user_id: Optional[int] = None
    campaign_id: Optional[int] = None
    internal_note: Optional[str] = None
    assigned_to_user_id: Optional[int] = None
    assigned_to_username: Optional[str] = None
    max_uses: int
    current_uses: int
    used_by_user_id: Optional[int] = None
    used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InviteValidate(BaseModel):
    """Schema for validating an invite code."""
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., max_length=64)


class InviteValidateResponse(BaseModel):
    """Schema for invite validation response."""
    valid: bool
    message: Optional[str] = None
    expires_at: Optional[datetime] = None


class InviteListResponse(BaseModel):
    """Schema for listing invite codes (admin only)."""
    invites: list[InviteRead]
    total: int
    limit: int
    offset: int


class MyInviteRead(BaseModel):
    id: int
    code: str
    status: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    used_at: Optional[datetime] = None
    invited_username: Optional[str] = None
    remaining_uses: int
    campaign_id: Optional[int] = None
    campaign_slug: Optional[str] = None
    campaign_name: Optional[str] = None


class MyInviteListResponse(BaseModel):
    invites: list[MyInviteRead]
