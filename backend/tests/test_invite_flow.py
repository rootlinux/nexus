import os
import secrets
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.models.invite import InviteType
from app.models.user import UserStatus
from app.services.invite_flow import resolve_inviter_user, validate_admin_invite_payload, validate_invite_state


def build_invite(**overrides):
    base = {
        "invite_type": InviteType.GENERIC,
        "is_active": True,
        "expires_at": None,
        "current_uses": 0,
        "max_uses": 1,
        "used_by_user_id": None,
        "used_at": None,
        "created_by_id": 1,
        "created_by_user": SimpleNamespace(id=1, username="admin", is_active=True, status=UserStatus.ACTIVE),
        "assigned_to_user": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class InviteFlowTests(unittest.TestCase):
    def test_admin_invite_payload_normalizes_internal_note(self):
        self.assertEqual(validate_admin_invite_payload("  beta cohort  "), "beta cohort")

    def test_admin_invite_payload_allows_empty_internal_note(self):
        self.assertIsNone(validate_admin_invite_payload("   "))

    def test_used_invite_is_rejected(self):
        invite = build_invite(current_uses=1)
        violation = validate_invite_state(invite)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.code, "used")
        self.assertEqual(violation.public_message, "This invite code is invalid or unavailable.")

    def test_admin_invite_is_valid_when_active_and_unused(self):
        invite = build_invite()
        self.assertIsNone(validate_invite_state(invite))

    def test_user_owned_invite_is_valid_when_owner_is_active(self):
        invite = build_invite(
            created_by_id=10,
            created_by_user=SimpleNamespace(id=10, username="owner", is_active=True, status=UserStatus.ACTIVE),
            assigned_to_user=SimpleNamespace(id=10, username="owner", is_active=True, status=UserStatus.ACTIVE),
        )
        self.assertIsNone(validate_invite_state(invite))

    def test_ineligible_inviter_is_rejected_by_policy(self):
        invite = build_invite(
            created_by_id=10,
            created_by_user=SimpleNamespace(id=10, username="owner", is_active=True, status=UserStatus.ACTIVE),
            assigned_to_user=SimpleNamespace(id=10, username="owner", is_active=False, status=UserStatus.SUSPENDED),
        )
        violation = validate_invite_state(invite)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.code, "policy")
        self.assertEqual(violation.public_message, "This invite code is invalid or unavailable.")

    def test_resolve_inviter_prefers_assigned_owner(self):
        invite = build_invite(
            created_by_user=SimpleNamespace(id=1, username="admin", is_active=True, status=UserStatus.ACTIVE),
            assigned_to_user=SimpleNamespace(id=22, username="curator", is_active=True, status=UserStatus.ACTIVE),
        )
        inviter = resolve_inviter_user(invite)
        self.assertIsNotNone(inviter)
        self.assertEqual(inviter.username, "curator")

    def test_expired_invite_is_rejected(self):
        invite = build_invite(expires_at=__import__("datetime").datetime(2000, 1, 1))
        violation = validate_invite_state(invite)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.code, "expired")
        self.assertEqual(violation.public_message, "This invite code is invalid or unavailable.")


if __name__ == "__main__":
    unittest.main()
