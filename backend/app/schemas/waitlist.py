from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class WaitlistApplicationCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    contact: str = Field(..., min_length=1, max_length=255)
    preferred_username: Optional[str] = Field(None, max_length=50)
    reason: str = Field(..., min_length=1, max_length=5000)
    referral_source: Optional[str] = Field(None, max_length=255)
    social_url: Optional[str] = Field(None, max_length=500)

    @field_validator("full_name", "reason")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        return value.strip()

    @field_validator("contact")
    @classmethod
    def normalize_contact(cls, value: str) -> str:
        cleaned = value.strip()
        if "@" in cleaned:
            local, domain = cleaned.rsplit("@", 1)
            # Strip "+tag" sub-addressing variant from local part
            if "+" in local:
                local = local.split("+", 1)[0]
            return f"{local.lower()}@{domain.lower()}"
        if any(c.isdigit() for c in cleaned):
            return "".join(c for c in cleaned if c.isdigit())
        return cleaned

    @field_validator("preferred_username", "referral_source", "social_url")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class WaitlistApplicationUpdate(BaseModel):
    status: Optional[str] = Field(None)
    admin_notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("admin_notes")
    @classmethod
    def normalize_admin_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class WaitlistApplicationResponse(BaseModel):
    id: int
    full_name: str
    contact: str
    preferred_username: Optional[str] = None
    reason: str
    referral_source: Optional[str] = None
    social_url: Optional[str] = None
    status: str
    admin_notes: Optional[str] = None
    invite_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WaitlistApplicationListResponse(BaseModel):
    applications: list[WaitlistApplicationResponse]
    total: int
    limit: int
    offset: int


class WaitlistInviteResponse(BaseModel):
    id: int
    code: str
    internal_note: Optional[str] = None
    created_by_id: int
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WaitlistInviteCreatedResponse(BaseModel):
    application_id: int
    invite: WaitlistInviteResponse
    message: str = "Invite created successfully"


class WaitlistInviteExistsResponse(BaseModel):
    application_id: int
    invite_id: int
    code: str
    message: str = "An invite already exists for this application"