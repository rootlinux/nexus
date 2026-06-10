from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class InviteCampaignBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    slug: str = Field(..., min_length=1, max_length=80)
    internal_note: str | None = Field(default=None, max_length=2000)
    public_label: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = False
    active_from: datetime | None = None
    expires_at: datetime | None = None
    max_uses_total: int | None = Field(default=None, ge=1)
    per_user_invite_allowance: int = Field(..., ge=1, le=100)

    @field_validator("name", "slug")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value is required")
        return cleaned

    @field_validator("internal_note", "public_label", "description")
    @classmethod
    def _normalize_optional_text_field(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _validate_window_order(self) -> "InviteCampaignBase":
        if self.active_from and self.expires_at and self.expires_at <= self.active_from:
            raise ValueError("expires_at must be later than active_from")
        return self


class InviteCampaignCreate(InviteCampaignBase):
    pass


class InviteCampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    internal_note: str | None = Field(default=None, max_length=2000)
    public_label: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    active_from: datetime | None = None
    expires_at: datetime | None = None
    max_uses_total: int | None = Field(default=None, ge=1)
    per_user_invite_allowance: int | None = Field(default=None, ge=1, le=100)

    @field_validator("name", "slug")
    @classmethod
    def _normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value is required")
        return cleaned

    @field_validator("internal_note", "public_label", "description")
    @classmethod
    def _normalize_optional_text_field(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _validate_window_order(self) -> "InviteCampaignUpdate":
        if self.active_from and self.expires_at and self.expires_at <= self.active_from:
            raise ValueError("expires_at must be later than active_from")
        return self


class CampaignInviteGenerateResponse(BaseModel):
    invite_id: int
    code: str
    campaign_id: int
    campaign_slug: str
    expires_at: datetime | None = None
    user_generated_count: int
    user_remaining_allowance: int


class InviteCampaignRead(BaseModel):
    id: int
    name: str
    slug: str
    internal_note: str | None = None
    public_label: str | None = None
    description: str | None = None
    is_active: bool
    active_from: datetime | None = None
    expires_at: datetime | None = None
    max_uses_total: int | None = None
    per_user_invite_allowance: int
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    generated_count: int = 0
    consumed_count: int = 0
    remaining_generation_capacity: int | None = None
    user_generated_count: int | None = None
    user_remaining_allowance: int | None = None

    model_config = ConfigDict(from_attributes=True)


class InviteCampaignListResponse(BaseModel):
    items: list[InviteCampaignRead]


class CampaignInviteRead(BaseModel):
    id: int
    code: str
    generated_by_user_id: int | None = None
    generated_by_username: str | None = None
    used_by_user_id: int | None = None
    used_by_username: str | None = None
    created_at: datetime
    used_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool


class CampaignRegistrationRead(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    created_at: datetime
    invited_by_user_id: int | None = None


class InviteCampaignDetail(InviteCampaignRead):
    invites: list[CampaignInviteRead]
    registrations: list[CampaignRegistrationRead]
