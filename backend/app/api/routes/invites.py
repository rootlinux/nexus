import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_interactive_user
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits
from app.models.invite import InviteCode
from app.models.invite_campaign import InviteCampaign
from app.models.user import User
from app.schemas.invite import MyInviteListResponse, MyInviteRead
from app.schemas.invite_campaign import CampaignInviteGenerateResponse, InviteCampaignListResponse, InviteCampaignRead
from app.services.audit import write_audit_log
from app.services.invite_campaigns import (
    CampaignRuleViolation,
    create_campaign_invite,
    get_campaign_counts,
    get_campaign_generation_count_for_user,
    validate_campaign_state,
)

router = APIRouter(prefix="/invites", tags=["invites"])


def _generate_invite_code(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _campaign_generation_policies(user_id: int, campaign_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="campaign-invite-generate-burst",
            limit=3,
            window_seconds=300,
            key=build_scope_key("campaign", "generate", "burst", user_id, campaign_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="campaign-invite-generate-sustained",
            limit=10,
            window_seconds=3600,
            key=build_scope_key("campaign", "generate", "sustained", user_id, campaign_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _campaign_read_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="campaign-read-burst",
            limit=20,
            window_seconds=60,
            key=build_scope_key("campaign", "read", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


@router.get("/me", response_model=MyInviteListResponse)
async def get_my_invites(
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(InviteCode)
        .options(
            selectinload(InviteCode.used_by_user),
            selectinload(InviteCode.campaign),
        )
        .where(
            or_(
                InviteCode.assigned_to_user_id == current_user.id,
                InviteCode.assigned_to_username == current_user.username,
            )
        )
        .order_by(InviteCode.created_at.desc(), InviteCode.id.desc())
    )
    invites = result.scalars().all()

    return MyInviteListResponse(
        invites=[
            MyInviteRead(
                id=invite.id,
                code=invite.code,
                status=(
                    "used"
                    if invite.current_uses >= invite.max_uses or invite.used_by_user_id is not None or invite.used_at is not None
                    else "expired"
                    if invite.expires_at and invite.expires_at < now
                    else "inactive"
                    if not invite.is_active
                    else "active"
                ),
                created_at=invite.created_at,
                expires_at=invite.expires_at,
                used_at=invite.used_at,
                invited_username=invite.used_by_user.username if invite.used_by_user else None,
                remaining_uses=max(invite.max_uses - invite.current_uses, 0),
                campaign_id=invite.campaign_id,
                campaign_slug=invite.campaign.slug if invite.campaign else None,
                campaign_name=invite.campaign.name if invite.campaign else None,
            )
            for invite in invites
        ]
    )


@router.get("/campaigns", response_model=InviteCampaignListResponse)
async def list_available_campaigns(
    request: Request,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _campaign_read_policies(current_user.id))

    result = await db.execute(
        select(InviteCampaign)
        .order_by(InviteCampaign.created_at.desc(), InviteCampaign.id.desc())
    )
    campaigns = result.scalars().all()
    items: list[InviteCampaignRead] = []
    now = datetime.now(timezone.utc)

    for campaign in campaigns:
        counts = await get_campaign_counts(db, campaign.id)
        counts["remaining_generation_capacity"] = (
            max(campaign.max_uses_total - counts["generated_count"], 0)
            if campaign.max_uses_total is not None
            else None
        )
        user_generated_count = await get_campaign_generation_count_for_user(
            db,
            campaign_id=campaign.id,
            user_id=current_user.id,
        )
        try:
            validate_campaign_state(
                campaign,
                now=now,
                generated_count=counts["generated_count"],
                consumed_count=counts["consumed_count"],
            )
            is_active = True
        except CampaignRuleViolation:
            is_active = False

        if not is_active and user_generated_count == 0:
            continue

        items.append(
            InviteCampaignRead(
                id=campaign.id,
                name=campaign.name,
                slug=campaign.slug,
                internal_note=None,
                public_label=campaign.public_label,
                description=campaign.description,
                is_active=is_active,
                active_from=campaign.active_from,
                expires_at=campaign.expires_at,
                max_uses_total=campaign.max_uses_total,
                per_user_invite_allowance=campaign.per_user_invite_allowance,
                created_by_user_id=campaign.created_by_user_id,
                updated_by_user_id=campaign.updated_by_user_id,
                created_at=campaign.created_at,
                updated_at=campaign.updated_at,
                generated_count=counts["generated_count"],
                consumed_count=counts["consumed_count"],
                remaining_generation_capacity=counts["remaining_generation_capacity"],
                user_generated_count=user_generated_count,
                user_remaining_allowance=max(campaign.per_user_invite_allowance - user_generated_count, 0),
            )
        )

    return InviteCampaignListResponse(items=items)


@router.post("/campaigns/{campaign_id}/generate", response_model=CampaignInviteGenerateResponse, status_code=status.HTTP_201_CREATED)
async def generate_campaign_invite(
    campaign_id: int,
    request: Request,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _campaign_generation_policies(current_user.id, campaign_id))

    async with db.begin():
        campaign_result = await db.execute(
            select(InviteCampaign)
            .where(InviteCampaign.id == campaign_id)
            .with_for_update()
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found",
            )

        code = _generate_invite_code()
        while True:
            existing_result = await db.execute(select(InviteCode.id).where(InviteCode.code == code))
            if existing_result.scalar_one_or_none() is None:
                break
            code = _generate_invite_code()

        try:
            invite, counts = await create_campaign_invite(
                db,
                campaign=campaign,
                actor=current_user,
                code=code,
            )
        except CampaignRuleViolation as exc:
            await write_audit_log(
                db,
                action="campaign_invite_generation_denied",
                actor_user=current_user,
                target_type="invite_campaign",
                target_id=campaign.id,
                after={"campaign_id": campaign.id, "violation_code": exc.code},
                request=request,
                success=False,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=exc.public_message,
            ) from exc

        await write_audit_log(
            db,
            action="campaign_invite_generated",
            actor_user=current_user,
            target_type="invite",
            target_id=invite.id,
            after={
                "campaign_id": campaign.id,
                "generated_by_user_id": current_user.id,
                "user_generated_count": counts["user_generated_count"],
                "user_remaining_allowance": counts["user_remaining_allowance"],
            },
            request=request,
            success=True,
        )

    return CampaignInviteGenerateResponse(
        invite_id=invite.id,
        code=invite.code,
        campaign_id=campaign.id,
        campaign_slug=campaign.slug,
        expires_at=invite.expires_at,
        user_generated_count=counts["user_generated_count"],
        user_remaining_allowance=counts["user_remaining_allowance"],
    )
