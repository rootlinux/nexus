from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Capability
from app.models.invite import InviteCode
from app.models.staff_permission import StaffPermission, StaffRole

STAFF_PERMISSION_FIELDS = (
    "can_create_invites",
    "can_view_moderation_queue",
    "can_moderate_posts",
    "can_manage_invites",
    "can_manage_users",
    "can_suspend_users",
    "can_ban_users",
    "can_manage_moderators",
    "can_reset_passwords",
    "can_revoke_sessions",
    "can_create_wave_campaigns",
)

PHASE1_EDITABLE_PERMISSION_FIELDS = (
    "can_create_invites",
    "can_view_moderation_queue",
    "can_moderate_posts",
    "can_manage_invites",
    "can_manage_users",
    "can_suspend_users",
    "can_ban_users",
    "can_manage_moderators",
)

MAX_INVITE_QUOTA_MONTHLY = 500
STAFF_ROLE_RANK: dict[StaffRole, int] = {
    StaffRole.MODERATOR: 1,
    StaffRole.ADMIN: 2,
    StaffRole.SUPER_ADMIN: 3,
}

ROLE_DEFAULTS: dict[StaffRole, dict[str, Any]] = {
    StaffRole.SUPER_ADMIN: {
        "can_create_invites": True,
        "invite_quota_monthly": None,
        "can_view_moderation_queue": True,
        "can_moderate_posts": True,
        "can_manage_invites": True,
        "can_manage_users": True,
        "can_suspend_users": True,
        "can_ban_users": True,
        "can_manage_moderators": True,
        "can_reset_passwords": False,
        "can_revoke_sessions": False,
        "can_create_wave_campaigns": False,
    },
    StaffRole.ADMIN: {
        "can_create_invites": True,
        "invite_quota_monthly": None,
        "can_view_moderation_queue": True,
        "can_moderate_posts": True,
        "can_manage_invites": True,
        "can_manage_users": True,
        "can_suspend_users": True,
        "can_ban_users": True,
        "can_manage_moderators": True,
        "can_reset_passwords": False,
        "can_revoke_sessions": False,
        "can_create_wave_campaigns": False,
    },
    StaffRole.MODERATOR: {
        "can_create_invites": False,
        "invite_quota_monthly": 0,
        "can_view_moderation_queue": True,
        "can_moderate_posts": True,
        "can_manage_invites": False,
        "can_manage_users": False,
        "can_suspend_users": False,
        "can_ban_users": False,
        "can_manage_moderators": False,
        "can_reset_passwords": False,
        "can_revoke_sessions": False,
        "can_create_wave_campaigns": False,
    },
}

CAPABILITY_TO_STAFF_FIELD: dict[str, str | tuple[str, ...] | None] = {
    Capability.USER_READ_BASIC: None,
    Capability.USER_READ: None,
    Capability.USER_MODERATE: "can_manage_users",
    Capability.USER_READ_SENSITIVE_MASKED: None,
    Capability.INVITE_READ: ("can_manage_invites", "can_create_invites"),
    Capability.INVITE_MANAGE: "can_manage_invites",
    Capability.INVITE_CREATE: "can_create_invites",
    Capability.INVITE_ASSIGN: "can_manage_invites",
    Capability.INVITE_REVEAL_FULL: "can_manage_invites",
    Capability.INVITE_REVOKE: "can_manage_invites",
    Capability.MODERATION_FREEZE: "can_manage_users",
    Capability.MODERATION_SUSPEND: "can_suspend_users",
    Capability.MODERATION_BAN: "can_ban_users",
    Capability.MODERATION_USER_READ: None,
    Capability.MODERATION_POST_READ: ("can_view_moderation_queue", "can_moderate_posts"),
    Capability.MODERATION_POST_HIDE: "can_moderate_posts",
    Capability.MODERATION_POST_UNHIDE: "can_moderate_posts",
    Capability.MODERATION_POST_DELETE: "can_moderate_posts",
    Capability.MODERATION_SIGNAL_READ: "can_view_moderation_queue",
    Capability.MODERATION_SIGNAL_RESOLVE: ("can_view_moderation_queue", "can_moderate_posts"),
    Capability.ROLE_CHANGE: "can_manage_moderators",
    Capability.AUDIT_READ: None,
}


@dataclass(frozen=True)
class StaffActorContext:
    role: StaffRole
    permissions: StaffPermission | SimpleNamespace


def build_admin_response_flags(staff_permission: StaffPermission | SimpleNamespace | None) -> tuple[bool, str | None]:
    if staff_permission is None:
        return False, None

    role = staff_permission.role.value if isinstance(staff_permission.role, StaffRole) else staff_permission.role
    if role == StaffRole.SUPER_ADMIN.value:
        return True, "super_admin"
    if role == StaffRole.MODERATOR.value:
        return True, "moderator"
    return True, "invite_admin"


def derive_admin_response_flags(user) -> tuple[bool, str | None]:
    return build_admin_response_flags(get_staff_permission_record(user))


def staff_session_requires_security_key(user) -> bool:
    is_admin, _ = derive_admin_response_flags(user)
    return is_admin


def get_staff_permission_record(user) -> StaffPermission | None:
    if user is None:
        return None
    return getattr(user, "staff_permission", None)


def get_staff_actor_context(user) -> StaffActorContext | None:
    staff_permission = get_staff_permission_record(user)
    if staff_permission is None:
        return None
    return StaffActorContext(role=staff_permission.role, permissions=staff_permission)


def resolve_staff_role(user) -> StaffRole | None:
    context = get_staff_actor_context(user)
    return context.role if context else None


def user_is_staff(user) -> bool:
    return get_staff_permission_record(user) is not None


def get_staff_role_rank(role: StaffRole | None) -> int:
    if role is None:
        return 0
    return STAFF_ROLE_RANK[role]


def staff_has_permission(user, field_name: str) -> bool:
    staff_permission = get_staff_permission_record(user)
    if staff_permission is None:
        return False
    return bool(getattr(staff_permission, field_name, False))


def _matches_field_requirement(user, requirement: str | tuple[str, ...] | None) -> bool:
    if requirement is None:
        return user_is_staff(user)
    if isinstance(requirement, tuple):
        return any(staff_has_permission(user, field_name) for field_name in requirement)
    return staff_has_permission(user, requirement)


def staff_has_capability(user, capability: str) -> bool:
    requirement = CAPABILITY_TO_STAFF_FIELD.get(capability)
    if capability not in CAPABILITY_TO_STAFF_FIELD:
        return False
    return _matches_field_requirement(user, requirement)


def enforce_staff_capability(user, capability: str) -> None:
    if not staff_has_capability(user, capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )


def sanitize_invite_quota_monthly(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 0 or value > MAX_INVITE_QUOTA_MONTHLY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invite_quota_monthly must be between 0 and {MAX_INVITE_QUOTA_MONTHLY}",
        )
    return value


def build_staff_defaults(role: StaffRole) -> dict[str, Any]:
    return dict(ROLE_DEFAULTS[role])


def serialize_staff_permissions(staff_permission: StaffPermission | SimpleNamespace) -> dict[str, Any]:
    return {
        "role": staff_permission.role.value if isinstance(staff_permission.role, StaffRole) else staff_permission.role,
        "can_create_invites": bool(getattr(staff_permission, "can_create_invites", False)),
        "invite_quota_monthly": getattr(staff_permission, "invite_quota_monthly", None),
        "can_view_moderation_queue": bool(getattr(staff_permission, "can_view_moderation_queue", False)),
        "can_moderate_posts": bool(getattr(staff_permission, "can_moderate_posts", False)),
        "can_manage_invites": bool(getattr(staff_permission, "can_manage_invites", False)),
        "can_manage_users": bool(getattr(staff_permission, "can_manage_users", False)),
        "can_suspend_users": bool(getattr(staff_permission, "can_suspend_users", False)),
        "can_ban_users": bool(getattr(staff_permission, "can_ban_users", False)),
        "can_manage_moderators": bool(getattr(staff_permission, "can_manage_moderators", False)),
        "can_reset_passwords": bool(getattr(staff_permission, "can_reset_passwords", False)),
        "can_revoke_sessions": bool(getattr(staff_permission, "can_revoke_sessions", False)),
        "can_create_wave_campaigns": bool(getattr(staff_permission, "can_create_wave_campaigns", False)),
    }


def apply_staff_permission_updates(
    staff_permission: StaffPermission,
    *,
    role: StaffRole,
    invite_quota_monthly: int | None,
    updates: dict[str, bool],
    updated_by_user_id: int,
) -> None:
    defaults = build_staff_defaults(role)
    normalized_quota = defaults["invite_quota_monthly"] if invite_quota_monthly is None and role != StaffRole.MODERATOR else invite_quota_monthly
    staff_permission.role = role
    staff_permission.invite_quota_monthly = sanitize_invite_quota_monthly(normalized_quota)

    merged = {field_name: defaults[field_name] for field_name in STAFF_PERMISSION_FIELDS}
    merged.update({field_name: bool(value) for field_name, value in updates.items() if field_name in PHASE1_EDITABLE_PERMISSION_FIELDS})

    if role == StaffRole.MODERATOR:
        merged["can_manage_moderators"] = False

    for field_name, value in merged.items():
        setattr(staff_permission, field_name, value)

    if role in {StaffRole.ADMIN, StaffRole.SUPER_ADMIN} and staff_permission.invite_quota_monthly == 0:
        staff_permission.invite_quota_monthly = None

    staff_permission.updated_by_user_id = updated_by_user_id
    staff_permission.updated_at = datetime.now(timezone.utc)


def enforce_staff_assignment_permissions(
    actor,
    *,
    target_user,
    desired_role: StaffRole | None = None,
    existing_staff_permission: StaffPermission | None = None,
) -> None:
    enforce_staff_capability(actor, Capability.ROLE_CHANGE)

    actor_role = resolve_staff_role(actor)
    if actor_role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff session required")

    if target_user.id == actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own staff permissions")

    actor_rank = get_staff_role_rank(actor_role)
    target_rank = get_staff_role_rank(existing_staff_permission.role) if existing_staff_permission else 0
    desired_rank = get_staff_role_rank(desired_role) if desired_role else target_rank

    if target_rank >= actor_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot manage a staff member with an equal or higher role",
        )

    if desired_role is not None:
        if desired_role == StaffRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Super admin role cannot be assigned through this workflow",
            )
        if desired_rank >= actor_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot assign a role equal to or higher than your own",
            )


def enforce_staff_moderation_target(actor, target_user) -> None:
    if target_user.id == actor.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot moderate yourself")

    actor_role = resolve_staff_role(actor)
    if actor_role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff session required")

    target_staff_permission = get_staff_permission_record(target_user)
    if target_staff_permission is None:
        return

    actor_rank = get_staff_role_rank(actor_role)
    target_rank = get_staff_role_rank(target_staff_permission.role)
    if actor_rank <= target_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot moderate a staff user with an equal or higher role",
        )


def ensure_staff_invite_creation_allowed(actor, invites_created_this_month: int) -> None:
    enforce_staff_capability(actor, Capability.INVITE_CREATE)
    staff_permission = get_staff_permission_record(actor)
    if staff_permission is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff session required")

    if staff_permission.role != StaffRole.MODERATOR:
        return

    quota = staff_permission.invite_quota_monthly or 0
    if invites_created_this_month >= quota:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Monthly invite quota exceeded for this moderator account",
        )


async def count_staff_invites_created_this_month(db: AsyncSession, actor_user_id: int) -> int:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1)
    next_month = datetime(now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1, 1)

    result = await db.execute(
        select(func.count(InviteCode.id)).where(
            InviteCode.created_by_id == actor_user_id,
            InviteCode.created_at >= month_start,
            InviteCode.created_at < next_month,
        )
    )
    return int(result.scalar() or 0)
