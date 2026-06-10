from typing import Optional

from pydantic import BaseModel, Field, field_validator

class FeedbackReportRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=4000)
    current_path: Optional[str] = Field(None, max_length=300)
    username: Optional[str] = Field(None, max_length=64)
    device_info: Optional[str] = Field(None, max_length=500)
    contact_email: Optional[str] = Field(None, max_length=255)
    current_url: Optional[str] = Field(None, max_length=500)
    user_agent: Optional[str] = Field(None, max_length=500)
    standalone_mode: Optional[bool] = None
    occurred_at: Optional[str] = Field(None, max_length=64)
    app_version: Optional[str] = Field(None, max_length=120)

    @field_validator(
        "title",
        "description",
        "current_path",
        "username",
        "device_info",
        "current_url",
        "user_agent",
        "occurred_at",
        "app_version",
    )
    @classmethod
    def normalize_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned.lower()


class FeedbackAttachmentReference(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    access_url: str
