from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator


class WebAuthnCredentialRead(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WebAuthnRegisterBeginResponse(BaseModel):
    options: dict[str, Any]


class WebAuthnRegisterBeginRequest(BaseModel):
    name: str
    current_password: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Key name cannot be empty")
        if len(v) > 100:
            raise ValueError("Key name cannot exceed 100 characters")
        return v


class WebAuthnRecoveryRegisterBeginRequest(BaseModel):
    recovery_token: str


class WebAuthnRegisterCompleteRequest(BaseModel):
    credential: dict[str, Any]
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Key name cannot be empty")
        if len(v) > 100:
            raise ValueError("Key name cannot exceed 100 characters")
        return v


class WebAuthnRecoveryRegisterCompleteRequest(BaseModel):
    recovery_token: str
    credential: dict[str, Any]
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Key name cannot be empty")
        if len(v) > 100:
            raise ValueError("Key name cannot exceed 100 characters")
        return v


class WebAuthnCredentialDeleteRequest(BaseModel):
    current_password: str | None = None


class WebAuthnAuthBeginRequest(BaseModel):
    mfa_session_token: str


class WebAuthnAuthBeginResponse(BaseModel):
    options: dict[str, Any]


class WebAuthnAuthCompleteRequest(BaseModel):
    mfa_session_token: str
    credential: dict[str, Any]


class MFARequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_session_token: str
