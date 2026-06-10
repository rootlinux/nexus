import asyncio
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_capability
from app.core.authorization import Capability, user_has_capability
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import (
    AUTH_RATE_LIMIT_ERROR,
    RATE_LIMIT_ERROR,
    RateLimitPolicy,
    build_scope_key,
    enforce_rate_limits,
    get_client_ip,
    hash_key_part,
)
from app.models.invite import InviteCode, InviteType
from app.models.user import User
from app.services.audit import write_audit_log
from app.services.invite_flow import validate_admin_invite_payload, validate_invite_state
from app.services.invite_campaigns import get_campaign_counts
from app.services.staff_permissions import count_staff_invites_created_this_month, ensure_staff_invite_creation_allowed
from app.schemas.invite import (
    InviteCreate,
    InviteRead,
    InviteListResponse,
    InviteValidate,
    InviteValidateResponse,
)

router = APIRouter(tags=["invite"])


def generate_invite_code(length: int = 32) -> str:
    """Generate a cryptographically secure invite code with letters and digits."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def mask_invite_code(code: str | None) -> str | None:
    if not code:
        return code
    visible_tail = min(4, len(code))
    return f"{'*' * max(0, len(code) - visible_tail)}{code[-visible_tail:]}"


@router.post("/create", response_model=InviteRead, status_code=status.HTTP_201_CREATED)
async def create_invite(
    request: Request,
    invite_data: InviteCreate,
    current_user: User = Depends(require_capability(Capability.INVITE_CREATE)),
    db: AsyncSession = Depends(get_db)
):
    """Create a single-use admin invite code."""
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="invite-create-admin",
                limit=12,
                window_seconds=600,
                key=build_scope_key("invite", "create", "user", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )

    invites_created_this_month = await count_staff_invites_created_this_month(db, current_user.id)
    ensure_staff_invite_creation_allowed(current_user, invites_created_this_month)

    # Generate unique invite code
    code = generate_invite_code(settings.INVITE_CODE_LENGTH)
    
    # Ensure code is unique
    while True:
        result = await db.execute(
            select(InviteCode).where(InviteCode.code == code)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            break
        code = generate_invite_code(settings.INVITE_CODE_LENGTH)
    
    # Calculate expiration; default to 30 days if not specified
    expiry_days = invite_data.expires_days if invite_data.expires_days is not None else 30
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)

    internal_note = validate_admin_invite_payload(invite_data.internal_note)
    assigned_user = None
    normalized_assigned_username = invite_data.assigned_to_username.strip() if invite_data.assigned_to_username else None
    if invite_data.assigned_to_username:
        if not user_has_capability(current_user, Capability.INVITE_ASSIGN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action",
            )
        assigned_user_result = await db.execute(
            select(User).where(User.username == normalized_assigned_username)
        )
        assigned_user = assigned_user_result.scalar_one_or_none()
        if not assigned_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assigned invite owner is invalid or unavailable",
            )

    new_invite = InviteCode(
        code=code,
        invite_type=InviteType.GENERIC,
        created_by_id=current_user.id,
        internal_note=internal_note,
        assigned_to_user_id=assigned_user.id if assigned_user else None,
        assigned_to_username=assigned_user.username if assigned_user else None,
        max_uses=1,
        current_uses=0,
        expires_at=expires_at,
        is_active=True,
    )
    
    db.add(new_invite)
    await db.flush()
    await write_audit_log(
        db,
        action="invite_created_by_staff",
        actor_user=current_user,
        target_type="invite",
        target_id=new_invite.id,
        after={
            "created_by_user_id": new_invite.created_by_id,
            "assigned_to_user_id": new_invite.assigned_to_user_id,
            "assigned_to_username": new_invite.assigned_to_username,
            "expires_at": new_invite.expires_at.isoformat() if new_invite.expires_at else None,
            "is_active": new_invite.is_active,
            "max_uses": new_invite.max_uses,
            "invite_quota_monthly": getattr(getattr(current_user, "staff_permission", None), "invite_quota_monthly", None),
            "invites_created_this_month": invites_created_this_month + 1,
        },
        reason=internal_note,
        request=request,
        success=True,
    )
    if assigned_user:
        await write_audit_log(
            db,
            action="invite.assign",
            actor_user=current_user,
            target_type="invite",
            target_id=new_invite.id,
            after={"assigned_to_user_id": assigned_user.id, "assigned_to_username": assigned_user.username},
            reason=internal_note,
            request=request,
            success=True,
        )
    await db.commit()
    await db.refresh(new_invite)
    
    return new_invite


@router.get("/list", response_model=InviteListResponse)
async def list_invites(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_capability(Capability.INVITE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """List admin invite codes (paginated)."""
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="invite-list-admin",
                limit=30,
                window_seconds=60,
                key=build_scope_key("invite", "list", "user", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )

    total_result = await db.execute(select(func.count()).select_from(InviteCode))
    total = total_result.scalar_one()

    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.generated_by_user),
            selectinload(InviteCode.assigned_to_user),
            selectinload(InviteCode.campaign),
            selectinload(InviteCode.used_by_user),
        )
        .order_by(InviteCode.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    invites = result.scalars().all()

    return InviteListResponse(
        invites=[
            InviteRead.model_validate(
                {
                    **InviteRead.model_validate(invite).model_dump(),
                    "code": mask_invite_code(invite.code),
                }
            )
            for invite in invites
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    request: Request,
    code: str,
    current_user: User = Depends(require_capability(Capability.INVITE_REVOKE)),
    db: AsyncSession = Depends(get_db)
):
    """
    Revoke an invite code (admin only).
    
    - Requires admin privileges
    - Deactivates the invite code
    """
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="invite-revoke-admin",
                limit=12,
                window_seconds=600,
                key=build_scope_key("invite", "revoke", "user", current_user.id),
                message=RATE_LIMIT_ERROR,
            ),
        ],
    )

    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.assigned_to_user),
            selectinload(InviteCode.campaign),
        )
        .where(InviteCode.code == code)
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite code not found"
        )
    
    # Deactivate the invite
    before = {
        "is_active": invite.is_active,
        "assigned_to_user_id": invite.assigned_to_user_id,
    }
    invite.is_active = False
    await write_audit_log(
        db,
        action="invite.revoke",
        actor_user=current_user,
        target_type="invite",
        target_id=invite.id,
        before=before,
        after={"is_active": invite.is_active},
        reason=invite.internal_note,
        request=request,
        success=True,
    )
    await db.commit()
    
    return None


@router.post("/validate", response_model=InviteValidateResponse)
async def validate_invite(
    request: Request,
    body: InviteValidate,
    db: AsyncSession = Depends(get_db),
):
    """Validate an invite code for registration."""
    code = body.code
    await enforce_rate_limits(
        request,
        [
            RateLimitPolicy(
                name="invite-validate-ip",
                limit=12,
                window_seconds=300,
                key=build_scope_key("invite", "validate", "ip", hash_key_part(get_client_ip(request))),
                message=AUTH_RATE_LIMIT_ERROR,
                strategy="sliding_window",
                require_redis_in_production=True,
            ),
            RateLimitPolicy(
                name="invite-validate-code",
                limit=6,
                window_seconds=300,
                key=build_scope_key(
                    "invite",
                    "validate",
                    "code",
                    hash_key_part(get_client_ip(request)),
                    hash_key_part(code),
                ),
                message=AUTH_RATE_LIMIT_ERROR,
                strategy="sliding_window",
                require_redis_in_production=True,
            ),
        ],
    )

    _INVALID = InviteValidateResponse(valid=False, message="This invite code is invalid or unavailable.")

    if len(code) < 8:
        await asyncio.sleep(random.uniform(0.05, 0.15))
        return _INVALID

    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.created_by_user),
            selectinload(InviteCode.assigned_to_user),
        )
        .where(InviteCode.code == code)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        await asyncio.sleep(random.uniform(0.05, 0.15))
        return _INVALID

    campaign_generated_count = None
    campaign_consumed_count = None
    if invite.campaign_id is not None:
        campaign_counts = await get_campaign_counts(db, invite.campaign_id)
        campaign_generated_count = campaign_counts["generated_count"]
        campaign_consumed_count = campaign_counts["consumed_count"]

    violation = validate_invite_state(
        invite,
        campaign_generated_count=campaign_generated_count,
        campaign_consumed_count=campaign_consumed_count,
    )
    if violation:
        await asyncio.sleep(random.uniform(0.05, 0.15))
        return _INVALID

    return InviteValidateResponse(
        valid=True,
        message="Invite code accepted.",
        expires_at=invite.expires_at,
    )
