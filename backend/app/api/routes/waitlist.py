
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, hash_key_part
from app.models.waitlist_application import WaitlistApplication
from app.schemas.waitlist import WaitlistApplicationCreate, WaitlistApplicationResponse


router = APIRouter(prefix="/waitlist", tags=["waitlist"])


def _normalize_contact(contact: str) -> str:
    """Normalize contact (email or phone) for duplicate detection.

    - Emails: strip whitespace, lowercase, strip +tag from local part
    - Phone numbers: strip all non-digit characters
    """
    cleaned = contact.strip()
    if "@" in cleaned:
        local, domain = cleaned.rsplit("@", 1)
        # Strip "+tag" sub-addressing variant from local part
        if "+" in local:
            local = local.split("+", 1)[0]
        return f"{local.lower()}@{domain.lower()}"
    if any(c.isdigit() for c in cleaned):
        return "".join(c for c in cleaned if c.isdigit())
    return cleaned


def _waitlist_submit_policies(request: Request) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    return [
        RateLimitPolicy(
            name="waitlist-submit-ip-burst",
            limit=5,
            window_seconds=3600,
            key=build_scope_key("waitlist", "submit", "ip", ip_key, "burst"),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="waitlist-submit-ip-sustained",
            limit=10,
            window_seconds=86400,
            key=build_scope_key("waitlist", "submit", "ip", ip_key, "sustained"),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


@router.post("", response_model=WaitlistApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_waitlist_application(
    request: Request,
    application_data: WaitlistApplicationCreate,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _waitlist_submit_policies(request))

    normalized_contact = _normalize_contact(application_data.contact)

    existing = await db.execute(
        select(WaitlistApplication).where(WaitlistApplication.contact == normalized_contact)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An application with this contact already exists.",
        )

    new_application = WaitlistApplication(
        full_name=application_data.full_name,
        contact=normalized_contact,
        preferred_username=application_data.preferred_username,
        reason=application_data.reason,
        referral_source=application_data.referral_source,
        social_url=application_data.social_url,
    )
    db.add(new_application)
    await db.commit()
    await db.refresh(new_application)

    return new_application