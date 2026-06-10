import os
import secrets
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.models.staff_permission import StaffRole
from app.models.user import UserStatus
from app.services.invite_campaigns import (
    CampaignRuleViolation,
    compute_campaign_remaining_allowance,
    normalize_campaign_slug,
    validate_campaign_state,
)
from app.services.invite_flow import validate_invite_state


def build_campaign(**overrides):
    base = {
        "id": 101,
        "name": "Spring Wave",
        "slug": "spring-wave",
        "is_active": True,
        "active_from": None,
        "expires_at": None,
        "max_uses_total": 5,
        "per_user_invite_allowance": 2,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_invite(**overrides):
    base = {
        "is_active": True,
        "expires_at": None,
        "current_uses": 0,
        "max_uses": 1,
        "used_by_user_id": None,
        "used_at": None,
        "created_by_id": 1,
        "created_by_user": SimpleNamespace(id=1, username="admin", is_active=True, status=UserStatus.ACTIVE),
        "assigned_to_user": None,
        "campaign": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class InviteCampaignServiceTests(unittest.TestCase):
    def test_normalize_campaign_slug_slugifies_input(self):
        self.assertEqual(normalize_campaign_slug("  Spring Wave 2026!  "), "spring-wave-2026")

    def test_validate_campaign_state_rejects_inactive_campaign(self):
        with self.assertRaises(CampaignRuleViolation) as ctx:
            validate_campaign_state(build_campaign(is_active=False), generated_count=0, consumed_count=0)
        self.assertEqual(ctx.exception.code, "inactive")

    def test_validate_campaign_state_rejects_not_yet_active_campaign(self):
        with self.assertRaises(CampaignRuleViolation) as ctx:
            validate_campaign_state(
                build_campaign(active_from=datetime.utcnow() + timedelta(hours=1)),
                generated_count=0,
                consumed_count=0,
            )
        self.assertEqual(ctx.exception.code, "not_yet_active")

    def test_validate_campaign_state_rejects_expired_campaign(self):
        with self.assertRaises(CampaignRuleViolation) as ctx:
            validate_campaign_state(
                build_campaign(expires_at=datetime.utcnow() - timedelta(seconds=1)),
                generated_count=0,
                consumed_count=0,
            )
        self.assertEqual(ctx.exception.code, "expired")

    def test_validate_campaign_state_enforces_generation_limit_for_generation(self):
        with self.assertRaises(CampaignRuleViolation) as ctx:
            validate_campaign_state(build_campaign(max_uses_total=2), generated_count=2, consumed_count=1)
        self.assertEqual(ctx.exception.code, "generation_limit_reached")

    def test_validate_campaign_state_allows_existing_invite_consumption_after_generation_cap(self):
        validate_campaign_state(
            build_campaign(max_uses_total=2),
            generated_count=2,
            consumed_count=1,
            enforce_generation_limit=False,
        )

    def test_validate_campaign_state_rejects_consumption_after_total_use_cap(self):
        with self.assertRaises(CampaignRuleViolation) as ctx:
            validate_campaign_state(
                build_campaign(max_uses_total=2),
                generated_count=2,
                consumed_count=2,
                enforce_generation_limit=False,
            )
        self.assertEqual(ctx.exception.code, "campaign_limit_reached")

    def test_compute_remaining_allowance_never_goes_negative(self):
        self.assertEqual(
            compute_campaign_remaining_allowance(build_campaign(per_user_invite_allowance=2), user_generated_count=5),
            0,
        )

    def test_campaign_linked_invite_is_rejected_when_campaign_expires_before_consume(self):
        invite = build_invite(
            campaign=build_campaign(
                expires_at=datetime.utcnow() - timedelta(seconds=1),
                max_uses_total=10,
            ),
        )
        violation = validate_invite_state(invite, campaign_generated_count=3, campaign_consumed_count=1)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.code, "expired")

    def test_campaign_linked_invite_is_rejected_when_campaign_limit_is_consumed(self):
        invite = build_invite(campaign=build_campaign(max_uses_total=1))
        violation = validate_invite_state(invite, campaign_generated_count=1, campaign_consumed_count=1)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.code, "campaign_limit_reached")


if __name__ == "__main__":
    unittest.main()
