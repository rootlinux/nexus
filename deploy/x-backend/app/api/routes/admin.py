import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin_session, require_capability
from app.core.authorization import Capability, user_has_capability
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits
from app.models.admin_audit_log import AdminAuditLog
from app.models.invite_usage import InviteUsage
from app.models.invite import InviteCode
from app.models.invite_campaign import InviteCampaign
from app.models.dm import DirectMessage
from app.models.moderation_signal import (
    ModerationDetectionStatus,
    ModerationReviewStatus,
    ModerationSignal,
    ModerationSurface,
)
from app.models.post import Post, PostModerationStatus
from app.models.staff_permission import StaffRole
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.services.moderation import apply_post_moderation, apply_user_status
from app.services.admin_security import (
    ADMIN_PASSWORD_RESET_TOKEN_TTL_MINUTES,
    count_active_refresh_tokens_for_user,
    issue_admin_password_reset_token,
    revoke_all_refresh_tokens_for_user,
)
from app.services.audit import write_audit_log
from app.services.invite_campaigns import (
    ensure_campaign_management_allowed,
    get_campaign_counts,
    normalize_campaign_slug,
    normalize_optional_text,
)
from app.services.staff_permissions import (
    build_admin_response_flags,
    enforce_staff_moderation_target,
    serialize_staff_permissions,
    staff_has_capability,
    staff_has_permission,
)
from app.services.post_views import (
    annotate_posts_for_user,
    delete_post_closure,
    get_post_with_relations,
    post_query_options,
    post_to_read_schema,
    refresh_post_counts,
    visible_post_filter,
)
from app.schemas.user import UserBanRequest, UserFreezeRequest, UserSuspendRequest
from app.schemas.invite_campaign import InviteCampaignCreate, InviteCampaignDetail, InviteCampaignRead, InviteCampaignUpdate
from app.schemas.staff import AdminSessionRead, StaffCapabilityRead, StaffPermissionRead

router = APIRouter(prefix="/admin", tags=["admin"])


def _mask_id(value: str | int | None) -> str | None:
    """Return a 12-char SHA-256 prefix instead of the raw numeric ID.

    Audit log responses should not expose raw user/resource IDs to prevent
    enumeration and correlation attacks. The masked value is deterministic
    (safe for diffing log entries) but not reversible.
    """
    if value is None:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _admin_read_policies(user_id: int, scope: str) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name=f"admin-{scope}-read-burst",
            limit=30,
            window_seconds=60,
            key=build_scope_key("admin", scope, "read", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name=f"admin-{scope}-read-sustained",
            limit=180,
            window_seconds=600,
            key=build_scope_key("admin", scope, "read", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _admin_mutation_policies(user_id: int, scope: str, *, strict: bool = False) -> list[RateLimitPolicy]:
    burst_limit = 3 if strict else 8
    sustained_limit = 12 if strict else 40
    sustained_window = 600 if strict else 3600
    strategy = "sliding_window" if strict else "fixed_window"
    return [
        RateLimitPolicy(
            name=f"admin-{scope}-mutation-burst",
            limit=burst_limit,
            window_seconds=60,
            key=build_scope_key("admin", scope, "mutation", "burst", user_id),
            message=RATE_LIMIT_ERROR,
            strategy=strategy,
            require_redis_in_production=strict,
        ),
        RateLimitPolicy(
            name=f"admin-{scope}-mutation-sustained",
            limit=sustained_limit,
            window_seconds=sustained_window,
            key=build_scope_key("admin", scope, "mutation", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
            strategy=strategy,
            require_redis_in_production=strict,
        ),
    ]


@router.get("/session", response_model=AdminSessionRead)
async def get_admin_session(
    current_admin: User = Depends(require_admin_session),
):
    staff_permission = getattr(current_admin, "staff_permission", None)
    if staff_permission is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin session required")

    can_manage_campaigns = (
        staff_permission.role in {StaffRole.ADMIN, StaffRole.SUPER_ADMIN}
        and staff_has_capability(current_admin, Capability.INVITE_MANAGE)
    )

    return AdminSessionRead(
        user_id=current_admin.id,
        role=staff_permission.role,
        permissions=StaffPermissionRead(**serialize_staff_permissions(staff_permission)),
        capabilities=StaffCapabilityRead(
            can_read_users=staff_has_capability(current_admin, Capability.USER_READ),
            can_manage_users=staff_has_permission(current_admin, "can_manage_users"),
            can_suspend_users=staff_has_capability(current_admin, Capability.MODERATION_SUSPEND),
            can_ban_users=staff_has_capability(current_admin, Capability.MODERATION_BAN),
            can_read_invites=staff_has_capability(current_admin, Capability.INVITE_READ),
            can_create_invites=staff_has_capability(current_admin, Capability.INVITE_CREATE),
            can_assign_invites=staff_has_capability(current_admin, Capability.INVITE_ASSIGN),
            can_reveal_invite_codes=staff_has_capability(current_admin, Capability.INVITE_REVEAL_FULL),
            can_manage_campaigns=can_manage_campaigns,
            can_view_moderation_queue=staff_has_capability(current_admin, Capability.MODERATION_SIGNAL_READ),
            can_moderate_posts=staff_has_permission(current_admin, "can_moderate_posts"),
            can_manage_moderators=staff_has_capability(current_admin, Capability.ROLE_CHANGE),
        ),
    )


class PostModerationRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class AdminSearchResponse(BaseModel):
    users: list[dict]
    invites: list[dict]
    posts: list[dict]


class ModerationSignalActionRequest(BaseModel):
    action: str = Field(..., min_length=3, max_length=50)
    note: str | None = Field(default=None, max_length=500)


class SensitiveAdminActionRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class ForcedPasswordResetResponse(BaseModel):
    reset_token: str
    expires_at: datetime
    must_change_password: bool
    invalidated_reset_artifacts: int
    revoked_session_count: int


class SessionRevocationResponse(BaseModel):
    revoked_session_count: int


class AdminWebAuthnCredentialRead(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None
    credential_identifier: str


def mask_invite_code(code: str | None) -> str | None:
    if not code:
        return code
    visible_tail = min(4, len(code))
    return f"{'*' * max(0, len(code) - visible_tail)}{code[-visible_tail:]}"


def _format_webauthn_credential_identifier(credential: WebAuthnCredential) -> str:
    fingerprint = hashlib.sha256(bytes(credential.credential_id)).hexdigest()[:12]
    return f"webauthn:{fingerprint}"


def snapshot_user_state(user: User) -> dict:
    is_admin, admin_role = build_admin_response_flags(getattr(user, "staff_permission", None))
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status.value,
        "status_reason": user.status_reason,
        "status_changed_at": user.status_changed_at.isoformat() if user.status_changed_at else None,
        "status_changed_by_user_id": user.status_changed_by_user_id,
        "is_active": user.is_active,
        "must_change_password": bool(user.must_change_password),
        "is_admin": is_admin,
        "admin_role": admin_role,
        "banned_at": user.banned_at.isoformat() if user.banned_at else None,
        "ban_reason": user.ban_reason,
        "banned_by_user_id": user.banned_by_user_id,
    }


def snapshot_invite_state(
    invite: InviteCode,
    *,
    reveal_full: bool = False,
    can_reveal_code: bool = False,
) -> dict:
    code_value = invite.code if reveal_full else mask_invite_code(invite.code)
    return {
        "id": invite.id,
        "code": code_value,
        "campaign_id": invite.campaign_id,
        "campaign_slug": invite.campaign.slug if getattr(invite, "campaign", None) else None,
        "generated_by_user_id": invite.generated_by_user_id,
        "generated_by_username": invite.generated_by_user.username if getattr(invite, "generated_by_user", None) else None,
        "internal_note": invite.internal_note,
        "created_by_id": invite.created_by_id,
        "created_by_username": invite.created_by_user.username if invite.created_by_user else None,
        "assigned_to_user_id": invite.assigned_to_user_id,
        "assigned_to_username": invite.assigned_to_user.username if invite.assigned_to_user else invite.assigned_to_username,
        "current_uses": invite.current_uses,
        "used": invite.current_uses >= 1 or invite.used_by_user_id is not None or invite.used_at is not None,
        "used_by_user_id": invite.used_by_user_id,
        "used_by_username": invite.used_by_user.username if invite.used_by_user else None,
        "used_at": invite.used_at.isoformat() if invite.used_at else None,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "is_active": invite.is_active,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "can_reveal_code": can_reveal_code,
    }


def snapshot_campaign_state(
    campaign: InviteCampaign,
    *,
    generated_count: int,
    consumed_count: int,
) -> dict:
    remaining_generation_capacity = (
        max(campaign.max_uses_total - generated_count, 0)
        if campaign.max_uses_total is not None
        else None
    )
    return {
        "id": campaign.id,
        "name": campaign.name,
        "slug": campaign.slug,
        "internal_note": campaign.internal_note,
        "public_label": campaign.public_label,
        "description": campaign.description,
        "is_active": campaign.is_active,
        "active_from": campaign.active_from.isoformat() if campaign.active_from else None,
        "expires_at": campaign.expires_at.isoformat() if campaign.expires_at else None,
        "max_uses_total": campaign.max_uses_total,
        "per_user_invite_allowance": campaign.per_user_invite_allowance,
        "created_by_user_id": campaign.created_by_user_id,
        "updated_by_user_id": campaign.updated_by_user_id,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "generated_count": generated_count,
        "consumed_count": consumed_count,
        "remaining_generation_capacity": remaining_generation_capacity,
    }


def _post_reference_ids(post: Post) -> set[int]:
    return {
        reference_id
        for reference_id in (post.parent_id, post.repost_of_id)
        if reference_id is not None
    }


def snapshot_post_state(post: Post) -> dict:
    return {
        "id": post.id,
        "user_id": post.user_id,
        "author_username": post.author.username if getattr(post, "author", None) else None,
        "parent_id": post.parent_id,
        "repost_of_id": post.repost_of_id,
        "is_repost": post.is_repost,
        "content": post.content,
        "media_url": post.media_url,
        "moderation_status": post.moderation_status.value,
        "moderation_reason": post.moderation_reason,
        "moderated_at": post.moderated_at.isoformat() if post.moderated_at else None,
        "moderated_by_user_id": post.moderated_by_user_id,
        "likes_count": post.likes_count,
        "replies_count": post.replies_count,
        "reposts_count": post.reposts_count,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }


def snapshot_signal_state(signal: ModerationSignal) -> dict:
    return {
        "id": signal.id,
        "user_id": signal.user_id,
        "post_id": signal.post_id,
        "dm_message_id": signal.dm_message_id,
        "surface_type": signal.surface_type.value,
        "detection_status": signal.detection_status.value,
        "review_status": signal.review_status.value,
        "reason_codes": signal.reason_codes or [],
        "reason_summary": signal.reason_summary,
        "risk_score": signal.risk_score,
        "content_preview": signal.content_preview,
        "media_url": signal.media_url,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "resolved_at": signal.resolved_at.isoformat() if signal.resolved_at else None,
        "resolved_by_user_id": signal.resolved_by_user_id,
        "resolution_action": signal.resolution_action,
        "resolution_note": signal.resolution_note,
    }


def _serialize_signal_summary(signal: ModerationSignal) -> dict:
    return {
        **snapshot_signal_state(signal),
        "is_media_signal": signal.surface_type in {
            ModerationSurface.PROFILE_AVATAR,
            ModerationSurface.PROFILE_COVER,
            ModerationSurface.POST_MEDIA,
            ModerationSurface.DM_MEDIA,
        },
        "has_media_preview": bool(signal.media_url),
        "actor_user": {
            "id": signal.actor_user.id,
            "username": signal.actor_user.username,
            "display_name": signal.actor_user.display_name,
            "status": signal.actor_user.status.value,
        } if signal.actor_user else None,
    }


async def _get_recent_media_signal_counts(db: AsyncSession, *, user_id: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    base_query = (
        select(func.count(ModerationSignal.id))
        .where(
            ModerationSignal.user_id == user_id,
            ModerationSignal.surface_type.in_([
                ModerationSurface.PROFILE_AVATAR,
                ModerationSurface.PROFILE_COVER,
                ModerationSurface.POST_MEDIA,
                ModerationSurface.DM_MEDIA,
            ]),
            ModerationSignal.created_at >= cutoff,
        )
    )

    suspicious_result = await db.execute(
        base_query.where(ModerationSignal.detection_status == ModerationDetectionStatus.SUSPICIOUS)
    )
    blocked_result = await db.execute(
        base_query.where(ModerationSignal.detection_status == ModerationDetectionStatus.BLOCKED)
    )

    return {
        "window_days": 30,
        "recent_suspicious_media_signals": int(suspicious_result.scalar() or 0),
        "recent_blocked_media_signals": int(blocked_result.scalar() or 0),
    }


def _require_signal_action_capability(current_admin: User, action: str) -> None:
    required_capability = Capability.MODERATION_SIGNAL_RESOLVE
    if action == "hide_post":
        required_capability = Capability.MODERATION_POST_HIDE
    elif action == "delete_post":
        required_capability = Capability.MODERATION_POST_DELETE
    elif action == "freeze_user":
        required_capability = Capability.MODERATION_FREEZE
    elif action == "suspend_user":
        required_capability = Capability.MODERATION_SUSPEND
    elif action == "ban_user":
        required_capability = Capability.MODERATION_BAN

    if not user_has_capability(current_admin, required_capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )


async def get_target_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.staff_permission))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def validate_target_user_for_moderation(target_user: User, current_admin: User) -> None:
    enforce_staff_moderation_target(current_admin, target_user)


def _can_apply_sensitive_user_action(current_admin: User, target_user: User, permission_field: str) -> bool:
    try:
        if not getattr(getattr(current_admin, "staff_permission", None), permission_field, False):
            return False
        validate_target_user_for_moderation(target_user, current_admin)
    except HTTPException:
        return False
    return True


def _require_super_admin(current_admin: User) -> None:
    role = getattr(getattr(current_admin, "staff_permission", None), "role", None)
    if role not in {StaffRole.SUPER_ADMIN, StaffRole.SUPER_ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )


@router.get("/search", response_model=AdminSearchResponse)
async def admin_global_search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "search"))

    normalized_query = q.strip()
    escaped_query = _escape_like_pattern(normalized_query)
    query = f"%{escaped_query}%"
    users: list[dict] = []
    invites: list[dict] = []
    posts: list[dict] = []

    if user_has_capability(current_admin, Capability.USER_READ):
        users_result = await db.execute(
            select(User)
            .where(
                or_(
                    User.username.ilike(query, escape="\\"),
                    User.display_name.ilike(query, escape="\\"),
                    User.email.ilike(query, escape="\\"),
                )
            )
            .order_by(User.created_at.desc())
            .limit(8)
        )
        users = [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "status": user.status.value,
            }
            for user in users_result.scalars().all()
        ]

    if user_has_capability(current_admin, Capability.INVITE_READ):
        suffix_query = f"%{_escape_like_pattern(normalized_query[-8:])}%"
        invites_result = await db.execute(
            select(InviteCode)
            .options(
                selectinload(InviteCode.created_by_user),
                selectinload(InviteCode.assigned_to_user),
                selectinload(InviteCode.used_by_user),
            )
            .where(
                or_(
                    InviteCode.code.ilike(suffix_query, escape="\\"),
                    InviteCode.internal_note.ilike(query, escape="\\"),
                    InviteCode.assigned_to_username.ilike(query, escape="\\"),
                    InviteCode.assigned_to_user.has(User.username.ilike(query, escape="\\")),
                    InviteCode.created_by_user.has(User.username.ilike(query, escape="\\")),
                    InviteCode.used_by_user.has(User.username.ilike(query, escape="\\")),
                )
            )
            .order_by(InviteCode.created_at.desc())
            .limit(8)
        )
        invites = [
            {
                "id": invite.id,
                "code": mask_invite_code(invite.code),
                "internal_note": invite.internal_note,
                "created_by_username": invite.created_by_user.username if invite.created_by_user else None,
                "assigned_to_username": invite.assigned_to_user.username if invite.assigned_to_user else invite.assigned_to_username,
                "used_by_username": invite.used_by_user.username if invite.used_by_user else None,
                "created_at": invite.created_at,
            }
            for invite in invites_result.scalars().all()
        ]

    if user_has_capability(current_admin, Capability.MODERATION_POST_READ):
        posts_result = await db.execute(
            select(Post)
            .options(*post_query_options())
            .where(Post.content.ilike(query, escape="\\"))
            .order_by(Post.created_at.desc())
            .limit(10)
        )
        post_rows = posts_result.scalars().all()
        await annotate_posts_for_user(db, post_rows, current_admin.id)
        posts = [
            {
                "id": post.id,
                "content_preview": (post.content or "")[:160],
                "created_at": post.created_at,
                "author_username": post.author.username if post.author else None,
                "is_repost": post.is_repost,
                "repost_of_id": post.repost_of_id,
                "parent_id": post.parent_id,
            }
            for post in post_rows
        ]

    return AdminSearchResponse(users=users, invites=invites, posts=posts)


# ==================== User Moderation Endpoints ====================

@router.get("/users", response_model=List[dict])
async def list_users(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[UserStatus] = Query(None, description="Filter by user status"),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.USER_READ))
):
    """
    List all users with moderation fields.
    
    Supports pagination and optional status filtering.
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "users"))

    query = (
        select(User)
        .options(selectinload(User.invite_used), selectinload(User.inviter), selectinload(User.staff_permission))
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    if status_filter:
        query = query.where(User.status == status_filter)
    
    result = await db.execute(query)
    users = result.scalars().all()
    
    users_data = []
    for user in users:
        is_admin, admin_role = build_admin_response_flags(getattr(user, "staff_permission", None))
        count_result = await db.execute(
            select(func.count(User.id)).where(User.invited_by_user_id == user.id)
        )
        invited_count = count_result.scalar() or 0

        users_data.append({
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "status": user.status.value,
            "is_active": user.is_active,
            "is_admin": is_admin,
            "admin_role": admin_role,
            "created_at": user.created_at,
            "banned_at": user.banned_at,
            "ban_reason": user.ban_reason,
            "banned_by_user_id": user.banned_by_user_id,
            "status_reason": user.status_reason,
            "status_changed_at": user.status_changed_at,
            "status_changed_by_user_id": user.status_changed_by_user_id,
            "invited_by_user_id": user.invited_by_user_id,
            "invited_by_username": user.inviter.username if user.inviter else None,
            "invite_id_used": user.invite_id_used,
            "invite_code_used": mask_invite_code(user.invite_used.code) if user.invite_used else None,
            "invited_users_count": invited_count,
        })

    return users_data


@router.get("/users/count")
async def count_users(
    request: Request,
    status_filter: Optional[UserStatus] = Query(None, description="Filter by user status"),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.USER_READ))
):
    """
    Get total count of users.
    
    Supports optional status filtering.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "users"))

    query = select(func.count(User.id))
    
    if status_filter:
        query = query.where(User.status == status_filter)
    
    result = await db.execute(query)
    count = result.scalar()
    return {"count": count}


@router.get("/users/{user_id}", response_model=dict)
async def get_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.USER_READ))
):
    """
    Get a specific user by ID with full moderation details.
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "users"))

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.inviter),
            selectinload(User.staff_permission),
            selectinload(User.invite_used).selectinload(InviteCode.created_by_user),
            selectinload(User.invite_used).selectinload(InviteCode.assigned_to_user),
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get banned by user info
    banned_by_user = None
    if user.banned_by_user_id:
        banned_result = await db.execute(
            select(User).where(User.id == user.banned_by_user_id)
        )
        banned_by = banned_result.scalar_one_or_none()
        if banned_by:
            banned_by_user = {
                "id": banned_by.id,
                "username": banned_by.username
            }
    
    count_result = await db.execute(
        select(func.count(User.id)).where(User.invited_by_user_id == user.id)
    )
    invited_count = count_result.scalar() or 0

    recent_posts_result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.user_id == user.id)
        .order_by(Post.created_at.desc())
        .limit(10)
    )
    recent_posts = recent_posts_result.scalars().all()
    await annotate_posts_for_user(db, recent_posts, current_admin.id)

    recent_post_ids = [str(post.id) for post in recent_posts]
    moderation_history_result = await db.execute(
        select(AdminAuditLog)
        .where(
            or_(
                (AdminAuditLog.target_type == "user") & (AdminAuditLog.target_id == str(user.id)),
                (AdminAuditLog.target_type == "post") & (AdminAuditLog.target_id.in_(recent_post_ids or ["-1"])),
            )
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(12)
    )
    moderation_history = moderation_history_result.scalars().all()
    is_admin, admin_role = build_admin_response_flags(getattr(user, "staff_permission", None))
    active_refresh_session_count = await count_active_refresh_tokens_for_user(db, user.id)
    can_force_password_reset = _can_apply_sensitive_user_action(current_admin, user, "can_reset_passwords")
    can_revoke_sessions = _can_apply_sensitive_user_action(current_admin, user, "can_revoke_sessions")

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "status": user.status.value,
        "is_active": user.is_active,
        "is_admin": is_admin,
        "admin_role": admin_role,
        "created_at": user.created_at,
        "banned_at": user.banned_at,
        "ban_reason": user.ban_reason,
        "banned_by_user_id": user.banned_by_user_id,
        "status_reason": user.status_reason,
        "status_changed_at": user.status_changed_at,
        "status_changed_by_user_id": user.status_changed_by_user_id,
        "must_change_password": bool(user.must_change_password),
        "banned_by_user": banned_by_user,
        "invited_by_user_id": user.invited_by_user_id,
        "invited_by_username": user.inviter.username if user.inviter else None,
        "invite_id_used": user.invite_id_used,
        "invite_used": {
            "id": user.invite_used.id,
            "code": mask_invite_code(user.invite_used.code),
            "internal_note": user.invite_used.internal_note,
            "created_by_id": user.invite_used.created_by_id,
            "created_by_username": user.invite_used.created_by_user.username if user.invite_used.created_by_user else None,
            "assigned_to_user_id": user.invite_used.assigned_to_user_id,
            "assigned_to_username": user.invite_used.assigned_to_user.username if user.invite_used.assigned_to_user else user.invite_used.assigned_to_username,
            "current_uses": user.invite_used.current_uses,
            "expires_at": user.invite_used.expires_at,
            "used_by_user_id": user.invite_used.used_by_user_id,
            "used_at": user.invite_used.used_at,
            "is_active": user.invite_used.is_active,
            "can_reveal_code": user_has_capability(current_admin, Capability.INVITE_REVEAL_FULL),
        } if user.invite_used else None,
        "invite_code_used": mask_invite_code(user.invite_used.code) if user.invite_used else None,
        "invited_users_count": invited_count,
        "invite_lineage": {
            "invited_by_user_id": user.invited_by_user_id,
            "invited_by_username": user.inviter.username if user.inviter else None,
            "invite_used_id": user.invite_used.id if user.invite_used else None,
            "invite_created_by_user_id": user.invite_used.created_by_id if user.invite_used else None,
            "invite_created_by_username": user.invite_used.created_by_user.username if user.invite_used and user.invite_used.created_by_user else None,
            "invite_assigned_to_username": user.invite_used.assigned_to_user.username if user.invite_used and user.invite_used.assigned_to_user else user.invite_used.assigned_to_username if user.invite_used else None,
        },
        "recent_posts": [post_to_read_schema(post, current_admin.id).model_dump(mode="json") for post in recent_posts],
        "active_refresh_session_count": active_refresh_session_count,
        "available_sensitive_actions": {
            "can_force_password_reset": can_force_password_reset,
            "can_revoke_sessions": can_revoke_sessions,
        },
        "moderation_history": [
            {
                "id": log.id,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": _mask_id(log.target_id),
                "reason": log.reason,
                "success": log.success,
                "created_at": log.created_at,
            }
            for log in moderation_history
        ],
    }


@router.post("/users/{user_id}/force-password-reset", response_model=ForcedPasswordResetResponse)
async def force_password_reset(
    request: Request,
    user_id: int,
    body: SensitiveAdminActionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "force-password-reset", strict=True))
    if not getattr(getattr(current_admin, "staff_permission", None), "can_reset_passwords", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this action")

    user = await get_target_user_or_404(db, user_id)
    validate_target_user_for_moderation(user, current_admin)

    before = snapshot_user_state(user)
    user.must_change_password = True
    reset_token, raw_secret, invalidated_count = await issue_admin_password_reset_token(
        db,
        user_id=user.id,
        issued_by_user_id=current_admin.id,
    )
    revoked_session_count = await revoke_all_refresh_tokens_for_user(db, user.id)

    await write_audit_log(
        db,
        action="password_reset_forced",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after={
            **snapshot_user_state(user),
            "invalidated_reset_artifacts": invalidated_count,
            "revoked_session_count": revoked_session_count,
        },
        reason=body.reason,
        request=request,
        success=True,
    )
    await write_audit_log(
        db,
        action="password_reset_token_issued",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        after={
            "reset_token_id": reset_token.id,
            "expires_at": reset_token.expires_at.isoformat(),
            "ttl_minutes": ADMIN_PASSWORD_RESET_TOKEN_TTL_MINUTES,
            "invalidated_reset_artifacts": invalidated_count,
        },
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()

    return ForcedPasswordResetResponse(
        reset_token=raw_secret,
        expires_at=reset_token.expires_at,
        must_change_password=True,
        invalidated_reset_artifacts=invalidated_count,
        revoked_session_count=revoked_session_count,
    )


@router.post("/users/{user_id}/revoke-sessions", response_model=SessionRevocationResponse)
async def revoke_user_sessions(
    request: Request,
    user_id: int,
    body: SensitiveAdminActionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "revoke-sessions", strict=True))
    if not getattr(getattr(current_admin, "staff_permission", None), "can_revoke_sessions", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this action")

    user = await get_target_user_or_404(db, user_id)
    validate_target_user_for_moderation(user, current_admin)

    revoked_count = await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="sessions_revoked",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        after={
            "revoked_session_count": revoked_count,
            "scope": "all_active_refresh_tokens",
        },
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()

    return SessionRevocationResponse(revoked_session_count=revoked_count)


@router.get("/users/{user_id}/webauthn-credentials", response_model=List[AdminWebAuthnCredentialRead])
async def list_user_webauthn_credentials(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "user-webauthn-credentials"))
    _require_super_admin(current_admin)

    user = await get_target_user_or_404(db, user_id)
    result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .order_by(WebAuthnCredential.created_at.asc(), WebAuthnCredential.id.asc())
    )
    credentials = result.scalars().all()
    return [
        AdminWebAuthnCredentialRead(
            id=credential.id,
            name=credential.name,
            created_at=credential.created_at,
            last_used_at=credential.last_used_at,
            credential_identifier=_format_webauthn_credential_identifier(credential),
        )
        for credential in credentials
    ]


@router.delete("/users/{user_id}/webauthn-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_webauthn_credential(
    request: Request,
    user_id: int,
    credential_id: int,
    body: SensitiveAdminActionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-webauthn-credentials", strict=True))
    _require_super_admin(current_admin)

    user = await get_target_user_or_404(db, user_id)
    credential_result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.id == credential_id,
            WebAuthnCredential.user_id == user.id,
        )
    )
    credential = credential_result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security key not found")

    await db.delete(credential)
    await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="webauthn.admin_key_removed",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        reason=body.reason,
        after={
            "credential_db_id": credential.id,
            "key_name": credential.name,
        },
        request=request,
        success=True,
    )
    await db.commit()
    return None


@router.post("/users/{user_id}/ban")
async def ban_user(
    request: Request,
    user_id: int,
    ban_request: UserBanRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_BAN))
):
    """
    Ban a user.
    
    - Sets user status to BANNED
    - Records banned_at timestamp
    - Records ban_reason
    - Records banned_by_user_id
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-ban", strict=True))
    user = await get_target_user_or_404(db, user_id)
    validate_target_user_for_moderation(user, current_admin)
    before = snapshot_user_state(user)
    apply_user_status(user, status=UserStatus.BANNED, actor_user_id=current_admin.id, reason=ban_request.reason)
    await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="user_banned",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=snapshot_user_state(user),
        reason=ban_request.reason,
        request=request,
        success=True,
    )
    await db.commit()
    
    return {
        "message": "User banned successfully",
        "user_id": user.id,
        "username": user.username,
        "status": user.status.value,
        "banned_at": user.banned_at,
        "ban_reason": user.ban_reason
    }


@router.post("/users/{user_id}/unban")
async def unban_user(
    request: Request,
    user_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_BAN))
):
    """
    Unban a user.
    
    - Sets user status back to ACTIVE
    - Clears banned_at, ban_reason, and banned_by_user_id
    - Reactivates the account
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-unban", strict=True))
    user = await get_target_user_or_404(db, user_id)
    if user.status != UserStatus.BANNED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not banned"
        )
    validate_target_user_for_moderation(user, current_admin)
    
    before = snapshot_user_state(user)

    apply_user_status(user, status=UserStatus.ACTIVE, actor_user_id=current_admin.id, reason=None)
    await write_audit_log(
        db,
        action="user_unbanned",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=snapshot_user_state(user),
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()
    
    return {
        "message": "User unbanned successfully",
        "user_id": user.id,
        "username": user.username,
        "status": user.status.value
    }


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    request: Request,
    user_id: int,
    suspend_request: UserSuspendRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_SUSPEND))
):
    """
    Suspend a user.
    
    - Sets user status to SUSPENDED
    - Records suspension reason
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-suspend", strict=True))
    user = await get_target_user_or_404(db, user_id)
    validate_target_user_for_moderation(user, current_admin)
    before = snapshot_user_state(user)
    apply_user_status(user, status=UserStatus.SUSPENDED, actor_user_id=current_admin.id, reason=suspend_request.reason)
    await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="user_suspended",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=snapshot_user_state(user),
        reason=suspend_request.reason,
        request=request,
        success=True,
    )
    await db.commit()
    
    return {
        "message": "User suspended successfully",
        "user_id": user.id,
        "username": user.username,
        "status": user.status.value,
        "reason": user.status_reason
    }


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    request: Request,
    user_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_SUSPEND))
):
    """
    Unsuspend a user (lift suspension).
    
    - Sets user status back to ACTIVE
    - Clears suspension reason
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-unsuspend", strict=True))
    user = await get_target_user_or_404(db, user_id)
    if user.status != UserStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not suspended"
        )
    validate_target_user_for_moderation(user, current_admin)
    
    before = snapshot_user_state(user)

    apply_user_status(user, status=UserStatus.ACTIVE, actor_user_id=current_admin.id, reason=None)
    await write_audit_log(
        db,
        action="user_unsuspended",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=snapshot_user_state(user),
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()
    
    return {
        "message": "User suspension lifted successfully",
        "user_id": user.id,
        "username": user.username,
        "status": user.status.value
    }


@router.post("/users/{user_id}/freeze")
async def freeze_user(
    request: Request,
    user_id: int,
    body: UserFreezeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_FREEZE))
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-freeze", strict=True))
    user = await get_target_user_or_404(db, user_id)
    validate_target_user_for_moderation(user, current_admin)
    before = snapshot_user_state(user)
    apply_user_status(user, status=UserStatus.FROZEN, actor_user_id=current_admin.id, reason=body.reason)
    await revoke_all_refresh_tokens_for_user(db, user.id)
    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after={**snapshot_user_state(user), "action": "freeze_user"},
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()
    return {"message": "User frozen successfully", "user_id": user.id, "status": user.status.value}


@router.post("/users/{user_id}/unfreeze")
async def unfreeze_user(
    request: Request,
    user_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_FREEZE))
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "user-unfreeze", strict=True))
    user = await get_target_user_or_404(db, user_id)
    if user.status != UserStatus.FROZEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not frozen")
    validate_target_user_for_moderation(user, current_admin)
    before = snapshot_user_state(user)
    apply_user_status(user, status=UserStatus.ACTIVE, actor_user_id=current_admin.id, reason=None)
    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after={**snapshot_user_state(user), "action": "unfreeze_user"},
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()
    return {"message": "User unfrozen successfully", "user_id": user.id, "status": user.status.value}


@router.get("/posts/{post_id}", response_model=dict)
async def get_post_moderation_detail(
    request: Request,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_POST_READ)),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "posts"))
    post = await get_post_with_relations(db, post_id, current_admin.id, include_moderated=True)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    replies_result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.parent_id == post.id)
        .order_by(Post.created_at.asc())
        .limit(10)
    )
    replies = replies_result.scalars().all()
    await annotate_posts_for_user(db, replies, current_admin.id)

    reposts_result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.repost_of_id == post.id, Post.is_repost == True)
        .order_by(Post.created_at.desc())
        .limit(10)
    )
    reposts = reposts_result.scalars().all()
    await annotate_posts_for_user(db, reposts, current_admin.id)

    history_result = await db.execute(
        select(AdminAuditLog)
        .where(AdminAuditLog.target_type == "post", AdminAuditLog.target_id == str(post.id))
        .order_by(AdminAuditLog.created_at.desc())
        .limit(12)
    )
    history = history_result.scalars().all()

    return {
        "post": post_to_read_schema(post, current_admin.id).model_dump(mode="json"),
        "author": {
            "id": post.author.id,
            "username": post.author.username,
            "display_name": post.author.display_name,
        } if post.author else None,
        "parent_post": post_to_read_schema(post.parent, current_admin.id).model_dump(mode="json") if post.parent and post.parent.author else None,
        "original_post": post_to_read_schema(post.repost_of, current_admin.id).model_dump(mode="json") if post.repost_of and post.repost_of.author else None,
        "recent_replies": [post_to_read_schema(reply, current_admin.id).model_dump(mode="json") for reply in replies],
        "recent_reposts": [post_to_read_schema(repost, current_admin.id).model_dump(mode="json") for repost in reposts],
        "moderation_history": [
            {
                "id": log.id,
                "action": log.action,
                "reason": log.reason,
                "success": log.success,
                "created_at": log.created_at,
            }
            for log in history
        ],
    }


@router.post("/posts/{post_id}/hide")
async def hide_post(
    request: Request,
    post_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_POST_HIDE)),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "post-hide", strict=True))
    result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    before = snapshot_post_state(post)
    apply_post_moderation(
        post,
        status=PostModerationStatus.HIDDEN,
        actor_user_id=current_admin.id,
        reason=body.reason,
    )
    await refresh_post_counts(db, _post_reference_ids(post))

    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="post",
        target_id=post.id,
        before=before,
        after={**snapshot_post_state(post), "action": "hide_post"},
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()

    return {"message": "Post hidden", "post": post_to_read_schema(post, current_admin.id).model_dump(mode="json")}


@router.post("/posts/{post_id}/unhide")
async def unhide_post(
    request: Request,
    post_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_POST_UNHIDE)),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "post-unhide", strict=True))
    result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.moderation_status != PostModerationStatus.HIDDEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Post is not hidden")

    before = snapshot_post_state(post)
    apply_post_moderation(
        post,
        status=PostModerationStatus.VISIBLE,
        actor_user_id=current_admin.id,
        reason=None,
    )
    await refresh_post_counts(db, _post_reference_ids(post))
    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="post",
        target_id=post.id,
        before=before,
        after={**snapshot_post_state(post), "action": "unhide_post"},
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()

    return {"message": "Post unhidden", "post": post_to_read_schema(post, current_admin.id).model_dump(mode="json")}


@router.post("/posts/{post_id}/delete")
async def delete_post_admin(
    request: Request,
    post_id: int,
    body: PostModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_POST_DELETE)),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "post-delete", strict=True))
    result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    before = snapshot_post_state(post)
    deletion_summary = await delete_post_closure(db, post, actor_user_id=current_admin.id, reason=body.reason)
    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="post",
        target_id=post.id,
        before=before,
        after={**deletion_summary, "action": "delete_post"},
        reason=body.reason,
        request=request,
        success=True,
    )
    await db.commit()

    return {"message": "Post deleted", **deletion_summary}


# ==================== Invite Management Endpoints ====================

@router.get("/invites", response_model=List[dict])
async def list_invites(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.INVITE_READ))
):
    """
    List all invites with core metadata.
    
    Includes inviter relationship and usage information.
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    query = (
        select(InviteCode)
        .options(
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.generated_by_user),
            selectinload(InviteCode.assigned_to_user),
            selectinload(InviteCode.campaign),
            selectinload(InviteCode.used_by_user),
            selectinload(InviteCode.usages),
        )
        .order_by(InviteCode.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    if is_active is not None:
        query = query.where(InviteCode.is_active == is_active)
    
    result = await db.execute(query)
    invites = result.scalars().all()
    
    # Build response with relationships
    can_reveal_code = user_has_capability(current_admin, Capability.INVITE_REVEAL_FULL)
    return [snapshot_invite_state(invite, can_reveal_code=can_reveal_code) for invite in invites]


@router.get("/invites/count")
async def count_invites(
    request: Request,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.INVITE_READ))
):
    """
    Get total count of invites.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    query = select(func.count(InviteCode.id))
    
    if is_active is not None:
        query = query.where(InviteCode.is_active == is_active)
    
    result = await db.execute(query)
    count = result.scalar()
    return {"count": count}


@router.get("/invites/{invite_id}", response_model=dict)
async def get_invite(
    request: Request,
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.INVITE_READ))
):
    """
    Get a specific invite by ID with full details.
    
    Includes inviter and used_by_user relationships.
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.used_by_user),
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.generated_by_user),
            selectinload(InviteCode.assigned_to_user),
            selectinload(InviteCode.campaign),
            selectinload(InviteCode.usages).selectinload(InviteUsage.used_by_user),
        )
        .where(InviteCode.id == invite_id)
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found"
        )

    registered_users_result = await db.execute(
        select(User)
        .where(User.invite_id_used == invite.id)
        .order_by(User.created_at.desc())
    )
    registered_users = registered_users_result.scalars().all()
    
    return {
        **snapshot_invite_state(
            invite,
            can_reveal_code=user_has_capability(current_admin, Capability.INVITE_REVEAL_FULL),
        ),
        "usage_history": [
            {
                "id": usage.id,
                "used_by_user_id": usage.used_by_user_id,
                "used_by_username": usage.used_by_user.username if usage.used_by_user else None,
                "used_at": usage.used_at,
            }
            for usage in sorted(invite.usages, key=lambda usage: usage.used_at, reverse=True)
        ],
        "registered_users": [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "status": user.status.value,
                "created_at": user.created_at,
                "invited_by_user_id": user.invited_by_user_id
            }
            for user in registered_users
        ],
    }


@router.post("/invites/{invite_id}/reveal", response_model=dict)
async def reveal_invite_code(
    request: Request,
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.INVITE_REVEAL_FULL))
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "invite-reveal", strict=True))

    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.generated_by_user),
            selectinload(InviteCode.assigned_to_user),
            selectinload(InviteCode.campaign),
            selectinload(InviteCode.used_by_user),
        )
        .where(InviteCode.id == invite_id)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found"
        )

    await write_audit_log(
        db,
        action="invite.reveal",
        actor_user=current_admin,
        target_type="invite",
        target_id=invite.id,
        after={"code": mask_invite_code(invite.code)},
        request=request,
        success=True,
    )
    await db.commit()

    return {"id": invite.id, "code": invite.code}


@router.get("/invite-campaigns", response_model=list[InviteCampaignRead])
async def list_invite_campaigns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    ensure_campaign_management_allowed(current_admin)
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invite-campaigns"))

    result = await db.execute(
        select(InviteCampaign)
        .order_by(InviteCampaign.created_at.desc(), InviteCampaign.id.desc())
    )
    campaigns = result.scalars().all()
    items: list[InviteCampaignRead] = []
    for campaign in campaigns:
        counts = await get_campaign_counts(db, campaign.id)
        items.append(InviteCampaignRead(**snapshot_campaign_state(campaign, **counts)))
    return items


@router.post("/invite-campaigns", response_model=InviteCampaignRead, status_code=status.HTTP_201_CREATED)
async def create_invite_campaign(
    payload: InviteCampaignCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    ensure_campaign_management_allowed(current_admin)
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "invite-campaign-create", strict=True))

    normalized_slug = normalize_campaign_slug(payload.slug)
    existing_result = await db.execute(select(InviteCampaign.id).where(InviteCampaign.slug == normalized_slug))
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign slug already exists")

    campaign = InviteCampaign(
        name=payload.name.strip(),
        slug=normalized_slug,
        internal_note=normalize_optional_text(payload.internal_note),
        public_label=normalize_optional_text(payload.public_label),
        description=normalize_optional_text(payload.description),
        is_active=payload.is_active,
        active_from=payload.active_from,
        expires_at=payload.expires_at,
        max_uses_total=payload.max_uses_total,
        per_user_invite_allowance=payload.per_user_invite_allowance,
        created_by_user_id=current_admin.id,
        updated_by_user_id=current_admin.id,
    )
    db.add(campaign)
    await db.flush()
    await write_audit_log(
        db,
        action="campaign_created",
        actor_user=current_admin,
        target_type="invite_campaign",
        target_id=campaign.id,
        after=snapshot_campaign_state(campaign, generated_count=0, consumed_count=0),
        reason=campaign.internal_note,
        request=request,
        success=True,
    )
    await db.commit()
    await db.refresh(campaign)
    return InviteCampaignRead(**snapshot_campaign_state(campaign, generated_count=0, consumed_count=0))


@router.get("/invite-campaigns/{campaign_id}", response_model=InviteCampaignDetail)
async def get_invite_campaign(
    campaign_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    ensure_campaign_management_allowed(current_admin)
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invite-campaigns"))

    result = await db.execute(select(InviteCampaign).where(InviteCampaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    counts = await get_campaign_counts(db, campaign.id)
    invites_result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.generated_by_user),
            selectinload(InviteCode.used_by_user),
        )
        .where(InviteCode.campaign_id == campaign.id)
        .order_by(InviteCode.created_at.desc(), InviteCode.id.desc())
    )
    invites = invites_result.scalars().all()

    registrations_result = await db.execute(
        select(User)
        .where(User.invite_id_used.in_(select(InviteCode.id).where(InviteCode.campaign_id == campaign.id)))
        .order_by(User.created_at.desc(), User.id.desc())
    )
    registrations = registrations_result.scalars().all()

    return InviteCampaignDetail(
        **snapshot_campaign_state(campaign, **counts),
        invites=[
            {
                "id": invite.id,
                "code": mask_invite_code(invite.code),
                "generated_by_user_id": invite.generated_by_user_id,
                "generated_by_username": invite.generated_by_user.username if invite.generated_by_user else None,
                "used_by_user_id": invite.used_by_user_id,
                "used_by_username": invite.used_by_user.username if invite.used_by_user else None,
                "created_at": invite.created_at,
                "used_at": invite.used_at,
                "expires_at": invite.expires_at,
                "is_active": invite.is_active,
            }
            for invite in invites
        ],
        registrations=[
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "created_at": user.created_at,
                "invited_by_user_id": user.invited_by_user_id,
            }
            for user in registrations
        ],
    )


@router.patch("/invite-campaigns/{campaign_id}", response_model=InviteCampaignRead)
async def update_invite_campaign(
    campaign_id: int,
    payload: InviteCampaignUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    ensure_campaign_management_allowed(current_admin)
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "invite-campaign-update", strict=True))

    result = await db.execute(
        select(InviteCampaign)
        .where(InviteCampaign.id == campaign_id)
        .with_for_update()
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    counts = await get_campaign_counts(db, campaign.id)
    before = snapshot_campaign_state(campaign, **counts)
    previous_active = campaign.is_active

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        campaign.name = updates["name"].strip()
    if "slug" in updates:
        normalized_slug = normalize_campaign_slug(updates["slug"])
        existing_slug_result = await db.execute(
            select(InviteCampaign.id).where(
                InviteCampaign.slug == normalized_slug,
                InviteCampaign.id != campaign.id,
            )
        )
        if existing_slug_result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign slug already exists")
        campaign.slug = normalized_slug
    if "internal_note" in updates:
        campaign.internal_note = normalize_optional_text(updates["internal_note"])
    if "public_label" in updates:
        campaign.public_label = normalize_optional_text(updates["public_label"])
    if "description" in updates:
        campaign.description = normalize_optional_text(updates["description"])
    if "is_active" in updates:
        campaign.is_active = updates["is_active"]
    if "active_from" in updates:
        campaign.active_from = updates["active_from"]
    if "expires_at" in updates:
        campaign.expires_at = updates["expires_at"]
    if "max_uses_total" in updates:
        campaign.max_uses_total = updates["max_uses_total"]
    if "per_user_invite_allowance" in updates:
        campaign.per_user_invite_allowance = updates["per_user_invite_allowance"]
    campaign.updated_by_user_id = current_admin.id
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()

    after = snapshot_campaign_state(campaign, **counts)
    await write_audit_log(
        db,
        action="campaign_updated",
        actor_user=current_admin,
        target_type="invite_campaign",
        target_id=campaign.id,
        before=before,
        after=after,
        reason=campaign.internal_note,
        request=request,
        success=True,
    )
    if previous_active != campaign.is_active:
        await write_audit_log(
            db,
            action="campaign_activated" if campaign.is_active else "campaign_deactivated",
            actor_user=current_admin,
            target_type="invite_campaign",
            target_id=campaign.id,
            before={"is_active": previous_active},
            after={"is_active": campaign.is_active},
            reason=campaign.internal_note,
            request=request,
            success=True,
        )
    await db.commit()
    await db.refresh(campaign)
    return InviteCampaignRead(**snapshot_campaign_state(campaign, **counts))


@router.get("/audit-logs", response_model=List[dict])
async def list_audit_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.AUDIT_READ))
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "audit"))
    result = await db.execute(
        select(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "actor_user_id": _mask_id(log.actor_user_id),
            "actor_role": log.actor_role,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": _mask_id(log.target_id),
            "reason": log.reason,
            "request_id": log.request_id,
            "ip_address": log.ip_address,
            "session_id": log.session_id,
            "success": log.success,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.get("/moderation/dashboard", response_model=dict)
async def moderation_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_SIGNAL_READ)),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "moderation"))
    open_suspicious_result = await db.execute(
        select(func.count(ModerationSignal.id)).where(
            ModerationSignal.review_status == ModerationReviewStatus.OPEN,
            ModerationSignal.detection_status == ModerationDetectionStatus.SUSPICIOUS,
        )
    )
    blocked_result = await db.execute(
        select(func.count(ModerationSignal.id)).where(
            ModerationSignal.review_status == ModerationReviewStatus.OPEN,
            ModerationSignal.detection_status == ModerationDetectionStatus.BLOCKED,
        )
    )
    newest_result = await db.execute(
        select(ModerationSignal)
        .options(selectinload(ModerationSignal.actor_user))
        .where(ModerationSignal.review_status == ModerationReviewStatus.OPEN)
        .order_by(ModerationSignal.created_at.desc())
        .limit(5)
    )
    newest_signals = newest_result.scalars().all()

    return {
        "open_suspicious_count": open_suspicious_result.scalar() or 0,
        "blocked_items_count": blocked_result.scalar() or 0,
        "newest_unresolved_items": [_serialize_signal_summary(signal) for signal in newest_signals],
    }


@router.get("/moderation/queue", response_model=List[dict])
async def list_moderation_queue(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    review_status: ModerationReviewStatus | None = Query(None),
    surface_type: ModerationSurface | None = Query(None),
    min_risk_score: int | None = Query(None, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_SIGNAL_READ)),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "moderation"))
    query = (
        select(ModerationSignal)
        .options(selectinload(ModerationSignal.actor_user))
        .order_by(ModerationSignal.risk_score.desc(), ModerationSignal.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if review_status is not None:
        query = query.where(ModerationSignal.review_status == review_status)
    if surface_type is not None:
        query = query.where(ModerationSignal.surface_type == surface_type)
    if min_risk_score is not None:
        query = query.where(ModerationSignal.risk_score >= min_risk_score)

    result = await db.execute(query)
    return [_serialize_signal_summary(signal) for signal in result.scalars().all()]


@router.get("/moderation/queue/{signal_id}", response_model=dict)
async def get_moderation_queue_item(
    request: Request,
    signal_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.MODERATION_SIGNAL_READ)),
):
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "moderation"))
    result = await db.execute(
        select(ModerationSignal)
        .options(
            selectinload(ModerationSignal.actor_user),
            selectinload(ModerationSignal.post).selectinload(Post.author),
            selectinload(ModerationSignal.dm_message).selectinload(DirectMessage.sender),
            selectinload(ModerationSignal.dm_message).selectinload(DirectMessage.receiver),
            selectinload(ModerationSignal.resolved_by_user),
        )
        .where(ModerationSignal.id == signal_id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation queue item not found")

    related_post = None
    if signal.post_id:
        related_post = await get_post_with_relations(db, signal.post_id, current_admin.id, include_moderated=True)

    detail_history_result = await db.execute(
        select(AdminAuditLog)
        .where(
            or_(
                (AdminAuditLog.target_type == "moderation_signal") & (AdminAuditLog.target_id == str(signal.id)),
                (AdminAuditLog.target_type == "post") & (AdminAuditLog.target_id == str(signal.post_id if signal.post_id else -1)),
                (AdminAuditLog.target_type == "user") & (AdminAuditLog.target_id == str(signal.user_id)),
            )
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(15)
    )
    detail_history = detail_history_result.scalars().all()

    dm_preview = None
    if signal.dm_message:
        dm_preview = {
            "id": signal.dm_message.id,
            "content": signal.dm_message.content,
            "created_at": signal.dm_message.created_at,
            "sender": {
                "id": signal.dm_message.sender.id,
                "username": signal.dm_message.sender.username,
            } if signal.dm_message.sender else None,
            "receiver": {
                "id": signal.dm_message.receiver.id,
                "username": signal.dm_message.receiver.username,
            } if signal.dm_message.receiver else None,
        }

    media_signal_counts = await _get_recent_media_signal_counts(db, user_id=signal.user_id)

    return {
        **_serialize_signal_summary(signal),
        "media_signal_counts": media_signal_counts,
        "media_preview_url": signal.media_url,
        "resolved_by_user": {
            "id": signal.resolved_by_user.id,
            "username": signal.resolved_by_user.username,
        } if signal.resolved_by_user else None,
        "target_post": post_to_read_schema(related_post, current_admin.id).model_dump(mode="json") if related_post else None,
        "target_dm_message": dm_preview,
        "available_actions": [
            "approve",
            "hide_post",
            "delete_post",
            "freeze_user",
            "suspend_user",
            "ban_user",
            "dismiss_signal",
        ],
        "audit_history": [
            {
                "id": log.id,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": _mask_id(log.target_id),
                "reason": log.reason,
                "success": log.success,
                "created_at": log.created_at,
            }
            for log in detail_history
        ],
    }


@router.post("/moderation/queue/{signal_id}/action", response_model=dict)
async def resolve_moderation_queue_item(
    request: Request,
    signal_id: int,
    body: ModerationSignalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _admin_mutation_policies(current_admin.id, "moderation-action", strict=True))
    action = body.action.strip()
    _require_signal_action_capability(current_admin, action)

    result = await db.execute(
        select(ModerationSignal)
        .options(selectinload(ModerationSignal.actor_user))
        .where(ModerationSignal.id == signal_id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation queue item not found")
    if signal.review_status != ModerationReviewStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Moderation queue item is already handled")

    before = snapshot_signal_state(signal)

    if action == "hide_post":
        if not signal.post_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This queue item is not linked to a post")
        post_result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == signal.post_id))
        post = post_result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        post_before = snapshot_post_state(post)
        apply_post_moderation(post, status=PostModerationStatus.HIDDEN, actor_user_id=current_admin.id, reason=body.note)
        await refresh_post_counts(db, _post_reference_ids(post))
        await write_audit_log(
            db,
            action="moderation_action_taken",
            actor_user=current_admin,
            target_type="post",
            target_id=post.id,
            before=post_before,
            after={**snapshot_post_state(post), "action": "hide_post"},
            reason=body.note,
            request=request,
            success=True,
        )
    elif action == "delete_post":
        if not signal.post_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This queue item is not linked to a post")
        post_result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == signal.post_id))
        post = post_result.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        post_before = snapshot_post_state(post)
        deletion_summary = await delete_post_closure(db, post, actor_user_id=current_admin.id, reason=body.note)
        await write_audit_log(
            db,
            action="moderation_action_taken",
            actor_user=current_admin,
            target_type="post",
            target_id=signal.post_id,
            before=post_before,
            after={**deletion_summary, "action": "delete_post"},
            reason=body.note,
            request=request,
            success=True,
        )
    elif action in {"freeze_user", "suspend_user", "ban_user"}:
        target_user = await get_target_user_or_404(db, signal.user_id)
        validate_target_user_for_moderation(target_user, current_admin)
        user_before = snapshot_user_state(target_user)
        if action == "freeze_user":
            apply_user_status(target_user, status=UserStatus.FROZEN, actor_user_id=current_admin.id, reason=body.note)
            audit_action = "moderation_action_taken"
        elif action == "suspend_user":
            apply_user_status(target_user, status=UserStatus.SUSPENDED, actor_user_id=current_admin.id, reason=body.note)
            audit_action = "user_suspended"
        else:
            apply_user_status(target_user, status=UserStatus.BANNED, actor_user_id=current_admin.id, reason=body.note)
            audit_action = "user_banned"
        await revoke_all_refresh_tokens_for_user(db, target_user.id)
        await write_audit_log(
            db,
            action=audit_action,
            actor_user=current_admin,
            target_type="user",
            target_id=target_user.id,
            before=user_before,
            after={**snapshot_user_state(target_user), "action": action},
            reason=body.note,
            request=request,
            success=True,
        )
    elif action not in {"approve", "dismiss_signal"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported moderation action")

    signal.review_status = (
        ModerationReviewStatus.DISMISSED if action == "dismiss_signal" else ModerationReviewStatus.RESOLVED
    )
    signal.resolved_at = datetime.now(timezone.utc)
    signal.resolved_by_user_id = current_admin.id
    signal.resolution_action = action
    signal.resolution_note = body.note

    await write_audit_log(
        db,
        action="moderation_action_taken",
        actor_user=current_admin,
        target_type="moderation_signal",
        target_id=signal.id,
        before=before,
        after={**snapshot_signal_state(signal), "action": action},
        reason=body.note,
        request=request,
        success=True,
    )
    await db.commit()

    return {"signal": _serialize_signal_summary(signal)}


@router.get("/users/{user_id}/invited-users", response_model=List[dict])
async def get_user_invited_users(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.INVITE_READ))
):
    """
    Get all users invited by a specific user.
    
    Returns the list of users who used this user's invite code.
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    # First check if user exists
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get all users invited by this user
    result = await db.execute(
        select(User)
        .options(selectinload(User.invite_used))
        .where(User.invited_by_user_id == user_id)
        .order_by(User.created_at.desc())
    )
    invited_users = result.scalars().all()
    
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "status": u.status.value,
            "created_at": u.created_at,
            "invite_id_used": u.invite_id_used,
            "invite_code": mask_invite_code(u.invite_used.code) if u.invite_used else None
        }
        for u in invited_users
    ]


@router.get("/users/{user_id}/invited-by", response_model=dict)
async def get_user_invited_by(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.USER_READ_BASIC))
):
    """
    Get the user who invited a specific user.
    
    Returns the inviter's information.
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if not user.invited_by_user_id or not user.inviter:
        return {
            "user_id": user_id,
            "invited_by_user_id": None,
            "inviter": None
        }
    
    return {
        "user_id": user_id,
        "invited_by_user_id": user.invited_by_user_id,
        "inviter": {
            "id": user.inviter.id,
            "username": user.inviter.username,
            "email": user.inviter.email,
            "status": user.inviter.status.value
        }
    }


@router.get("/users/{user_id}/invited-count", response_model=dict)
async def get_user_invited_count(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_capability(Capability.USER_READ_BASIC))
):
    """
    Get the count of users invited by a specific user.
    
    Only accessible by admin users.
    """
    await enforce_rate_limits(request, _admin_read_policies(current_admin.id, "invites"))

    # First check if user exists
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Count users invited by this user
    count_result = await db.execute(
        select(func.count(User.id)).where(User.invited_by_user_id == user_id)
    )
    count = count_result.scalar()
    
    return {
        "user_id": user_id,
        "invited_users_count": count
    }
