from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.staff_permission import StaffRole


class StaffPermissionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_create_invites: bool = False
    invite_quota_monthly: int | None = Field(default=0, ge=0, le=500)
    can_view_moderation_queue: bool = False
    can_moderate_posts: bool = False
    can_manage_invites: bool = False
    can_manage_users: bool = False
    can_suspend_users: bool = False
    can_ban_users: bool = False
    can_manage_moderators: bool = False


class StaffAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = Field(default=None, ge=1)
    username: str | None = Field(default=None, min_length=3, max_length=50)
    role: StaffRole
    permissions: StaffPermissionBase | None = None

    @model_validator(mode="after")
    def validate_role_permissions(self) -> "StaffAssignmentCreate":
        if self.role == StaffRole.MODERATOR and self.permissions and self.permissions.can_manage_moderators:
            raise ValueError("Moderators cannot be granted can_manage_moderators")
        return self


class StaffAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: StaffRole
    permissions: StaffPermissionBase
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_role_permissions(self) -> "StaffAssignmentUpdate":
        if self.role == StaffRole.MODERATOR and self.permissions.can_manage_moderators:
            raise ValueError("Moderators cannot be granted can_manage_moderators")
        return self


class StaffAssignmentRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class StaffPermissionRead(StaffPermissionBase):
    can_reset_passwords: bool = False
    can_revoke_sessions: bool = False
    can_create_wave_campaigns: bool = False
    role: StaffRole


class StaffUserSummary(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    email: str


class StaffAssignmentRead(BaseModel):
    id: int
    user: StaffUserSummary
    permissions: StaffPermissionRead
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None
    created_at: datetime
    updated_at: datetime
    can_edit: bool
    can_remove: bool


class StaffActorRead(BaseModel):
    user_id: int
    role: StaffRole
    permissions: StaffPermissionRead
    manageable_roles: list[StaffRole]


class StaffAssignmentListResponse(BaseModel):
    current_actor: StaffActorRead
    items: list[StaffAssignmentRead]


class StaffCapabilityRead(BaseModel):
    can_read_users: bool = False
    can_manage_users: bool = False
    can_suspend_users: bool = False
    can_ban_users: bool = False
    can_read_invites: bool = False
    can_create_invites: bool = False
    can_assign_invites: bool = False
    can_reveal_invite_codes: bool = False
    can_manage_campaigns: bool = False
    can_view_moderation_queue: bool = False
    can_moderate_posts: bool = False
    can_manage_moderators: bool = False


class AdminSessionRead(BaseModel):
    user_id: int
    role: StaffRole
    permissions: StaffPermissionRead
    capabilities: StaffCapabilityRead
