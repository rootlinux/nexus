from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.datetime_utils import ensure_utc_datetime
from app.models.invite import InviteCode
from app.models.user import User, UserStatus
from app.services.invite_campaigns import CampaignRuleViolation, validate_campaign_state


@dataclass
class InviteRuleViolation(Exception):
    code: str
    message: str
    public_message: str

    def __init__(self, code: str, message: str, public_message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.public_message = public_message


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def validate_admin_invite_payload(internal_note: Optional[str]) -> Optional[str]:
    return _normalize_text(internal_note)


def resolve_inviter_user(invite: InviteCode) -> User | None:
    assigned_user = getattr(invite, "assigned_to_user", None)
    if assigned_user is not None:
        return assigned_user
    return getattr(invite, "created_by_user", None)


def _is_user_eligible_inviter(user: User | None) -> bool:
    if user is None:
        return False
    return bool(user.is_active and user.status == UserStatus.ACTIVE)


_GENERIC_PUBLIC_MESSAGE = "This invite code is invalid or unavailable."


def validate_invite_state(
    invite: InviteCode,
    *,
    now: Optional[datetime] = None,
    campaign_generated_count: int | None = None,
    campaign_consumed_count: int | None = None,
) -> Optional[InviteRuleViolation]:
    now = now or datetime.now(timezone.utc)
    expires_at = ensure_utc_datetime(invite.expires_at)

    if invite.current_uses >= invite.max_uses or invite.used_by_user_id is not None or invite.used_at is not None:
        return InviteRuleViolation(
            "used",
            "Invite code has already been used",
            _GENERIC_PUBLIC_MESSAGE,
        )

    if expires_at and expires_at < now:
        return InviteRuleViolation(
            "expired",
            "Invite code has expired",
            _GENERIC_PUBLIC_MESSAGE,
        )

    if not invite.is_active:
        return InviteRuleViolation(
            "inactive",
            "Invite code is inactive",
            _GENERIC_PUBLIC_MESSAGE,
        )

    creator = getattr(invite, "created_by_user", None)
    if creator is None:
        return InviteRuleViolation(
            "misconfigured",
            "Invite code is misconfigured",
            _GENERIC_PUBLIC_MESSAGE,
        )

    inviter = resolve_inviter_user(invite)
    if not _is_user_eligible_inviter(inviter):
        return InviteRuleViolation(
            "policy",
            "Invite code is disallowed by invite policy",
            _GENERIC_PUBLIC_MESSAGE,
        )

    campaign = getattr(invite, "campaign", None)
    if campaign is not None:
        try:
            validate_campaign_state(
                campaign,
                now=now,
                generated_count=campaign_generated_count or 0,
                consumed_count=campaign_consumed_count or 0,
                enforce_generation_limit=False,
            )
        except CampaignRuleViolation as exc:
            return InviteRuleViolation(exc.code, exc.message, exc.public_message)

    return None
