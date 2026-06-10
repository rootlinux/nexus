from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetime_utils import ensure_utc_datetime
from app.core.authorization import Capability
from app.models.invite import InviteCode, InviteType
from app.models.invite_campaign import InviteCampaign
from app.models.staff_permission import StaffRole
from app.models.user import User, UserStatus
from app.services.staff_permissions import (
    count_staff_invites_created_this_month,
    ensure_staff_invite_creation_allowed,
    resolve_staff_role,
    user_is_staff,
)


SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
GENERIC_INVITE_UNAVAILABLE = "This invite code is invalid or unavailable."


@dataclass
class CampaignRuleViolation(Exception):
    code: str
    message: str
    public_message: str

    def __init__(self, code: str, message: str, public_message: str = GENERIC_INVITE_UNAVAILABLE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.public_message = public_message


def normalize_campaign_slug(value: str) -> str:
    normalized = SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign slug must contain letters or numbers",
        )
    if len(normalized) > 80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign slug must be 80 characters or fewer",
        )
    return normalized


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def ensure_campaign_management_allowed(actor: User) -> None:
    role = resolve_staff_role(actor)
    if role not in {StaffRole.ADMIN, StaffRole.SUPER_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )
    from app.core.authorization import user_has_capability

    if not user_has_capability(actor, Capability.INVITE_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )


async def get_campaign_counts(db: AsyncSession, campaign_id: int) -> dict[str, int]:
    generated_result = await db.execute(
        select(func.count(InviteCode.id)).where(InviteCode.campaign_id == campaign_id)
    )
    generated_count = int(generated_result.scalar_one() or 0)

    consumed_result = await db.execute(
        select(func.count(InviteCode.id)).where(
            InviteCode.campaign_id == campaign_id,
            InviteCode.used_by_user_id.is_not(None),
        )
    )
    consumed_count = int(consumed_result.scalar_one() or 0)

    return {
        "generated_count": generated_count,
        "consumed_count": consumed_count,
    }


async def get_campaign_generation_count_for_user(
    db: AsyncSession,
    *,
    campaign_id: int,
    user_id: int,
) -> int:
    result = await db.execute(
        select(func.count(InviteCode.id)).where(
            InviteCode.campaign_id == campaign_id,
            InviteCode.generated_by_user_id == user_id,
        )
    )
    return int(result.scalar_one() or 0)


def validate_campaign_state(
    campaign: InviteCampaign,
    *,
    now: datetime | None = None,
    generated_count: int = 0,
    consumed_count: int = 0,
    enforce_generation_limit: bool = True,
) -> None:
    now = now or datetime.now(timezone.utc)
    active_from = ensure_utc_datetime(campaign.active_from)
    expires_at = ensure_utc_datetime(campaign.expires_at)

    if not campaign.is_active:
        raise CampaignRuleViolation("inactive", "Campaign is inactive")
    if active_from and now < active_from:
        raise CampaignRuleViolation("not_yet_active", "Campaign is not active yet")
    if expires_at and now >= expires_at:
        raise CampaignRuleViolation("expired", "Campaign has expired")
    if campaign.max_uses_total is not None and enforce_generation_limit:
        if generated_count >= campaign.max_uses_total:
            raise CampaignRuleViolation("generation_limit_reached", "Campaign generation limit reached")
    if campaign.max_uses_total is not None:
        if consumed_count >= campaign.max_uses_total:
            raise CampaignRuleViolation("campaign_limit_reached", "Campaign consumption limit reached")


def compute_campaign_remaining_allowance(
    campaign: InviteCampaign,
    *,
    user_generated_count: int,
) -> int:
    remaining = campaign.per_user_invite_allowance - user_generated_count
    return max(remaining, 0)


def ensure_actor_can_generate_campaign_invite(actor: User, *, staff_invites_created_this_month: int | None = None) -> None:
    if not actor.is_active or actor.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    if user_is_staff(actor):
        if staff_invites_created_this_month is None:
            raise RuntimeError("staff_invites_created_this_month is required for staff actors")
        ensure_staff_invite_creation_allowed(actor, staff_invites_created_this_month)


async def create_campaign_invite(
    db: AsyncSession,
    *,
    campaign: InviteCampaign,
    actor: User,
    code: str,
    now: datetime | None = None,
) -> tuple[InviteCode, dict[str, int]]:
    now = now or datetime.now(timezone.utc)
    staff_invites_created_this_month = None
    if user_is_staff(actor):
        staff_invites_created_this_month = await count_staff_invites_created_this_month(db, actor.id)
    ensure_actor_can_generate_campaign_invite(
        actor,
        staff_invites_created_this_month=staff_invites_created_this_month,
    )

    counts = await get_campaign_counts(db, campaign.id)
    counts["remaining_generation_capacity"] = (
        max(campaign.max_uses_total - counts["generated_count"], 0)
        if campaign.max_uses_total is not None
        else -1
    )
    validate_campaign_state(
        campaign,
        now=now,
        generated_count=counts["generated_count"],
        consumed_count=counts["consumed_count"],
    )

    user_generated_count = await get_campaign_generation_count_for_user(
        db,
        campaign_id=campaign.id,
        user_id=actor.id,
    )
    remaining_allowance = compute_campaign_remaining_allowance(
        campaign,
        user_generated_count=user_generated_count,
    )
    if remaining_allowance <= 0:
        raise CampaignRuleViolation("allowance_exhausted", "Per-user campaign allowance exhausted")

    invite = InviteCode(
        code=code,
        invite_type=InviteType.REFERRAL,
        created_by_id=actor.id,
        generated_by_user_id=actor.id,
        assigned_to_user_id=actor.id,
        assigned_to_username=actor.username,
        campaign_id=campaign.id,
        internal_note=campaign.internal_note,
        max_uses=1,
        current_uses=0,
        expires_at=campaign.expires_at,
        is_active=True,
    )
    db.add(invite)
    await db.flush()

    counts["generated_count"] += 1
    counts["remaining_generation_capacity"] = (
        max(campaign.max_uses_total - counts["generated_count"], 0)
        if campaign.max_uses_total is not None
        else -1
    )
    counts["user_generated_count"] = user_generated_count + 1
    counts["user_remaining_allowance"] = max(remaining_allowance - 1, 0)
    return invite, counts
