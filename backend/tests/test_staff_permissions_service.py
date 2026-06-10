import os
import secrets
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://placeholder")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(16))

from app.core.authorization import Capability
from app.models.staff_permission import StaffRole
from app.models.webauthn_credential import WebAuthnCredential  # noqa: F401 — triggers mapper registration
from app.services.staff_permissions import (
    derive_admin_response_flags,
    count_staff_invites_created_this_month,
    ensure_staff_invite_creation_allowed,
    enforce_staff_assignment_permissions,
    enforce_staff_moderation_target,
    staff_has_capability,
    staff_session_requires_security_key,
)


def build_staff_user(
    user_id: int,
    role: StaffRole,
    **permissions,
):
    base_permissions = {
        "role": role,
        "can_create_invites": False,
        "invite_quota_monthly": 0,
        "can_view_moderation_queue": False,
        "can_moderate_posts": False,
        "can_manage_invites": False,
        "can_manage_users": False,
        "can_suspend_users": False,
        "can_ban_users": False,
        "can_manage_moderators": False,
        "can_reset_passwords": False,
        "can_revoke_sessions": False,
        "can_create_wave_campaigns": False,
    }
    base_permissions.update(permissions)
    return SimpleNamespace(
        id=user_id,
        username=f"user{user_id}",
        staff_permission=SimpleNamespace(**base_permissions),
    )


class StaffPermissionsServiceTests(unittest.TestCase):
    def test_super_admin_can_manage_admin_assignment(self):
        actor = build_staff_user(1, StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        target = SimpleNamespace(id=2, username="admin2", staff_permission=None)

        enforce_staff_assignment_permissions(
            actor,
            target_user=target,
            desired_role=StaffRole.ADMIN,
            existing_staff_permission=None,
        )

    def test_admin_can_manage_moderator_assignment(self):
        actor = build_staff_user(1, StaffRole.ADMIN, can_manage_moderators=True)
        target = SimpleNamespace(id=2, username="mod", staff_permission=None)

        enforce_staff_assignment_permissions(
            actor,
            target_user=target,
            desired_role=StaffRole.MODERATOR,
            existing_staff_permission=None,
        )

    def test_admin_cannot_assign_admin_role(self):
        actor = build_staff_user(1, StaffRole.ADMIN, can_manage_moderators=True)
        target = SimpleNamespace(id=2, username="admin2", staff_permission=None)

        with self.assertRaises(HTTPException) as ctx:
            enforce_staff_assignment_permissions(
                actor,
                target_user=target,
                desired_role=StaffRole.ADMIN,
                existing_staff_permission=None,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_manage_equal_role_staff_member(self):
        actor = build_staff_user(1, StaffRole.ADMIN, can_manage_moderators=True)
        target = build_staff_user(2, StaffRole.ADMIN, can_manage_moderators=True)

        with self.assertRaises(HTTPException) as ctx:
            enforce_staff_assignment_permissions(
                actor,
                target_user=target,
                desired_role=StaffRole.MODERATOR,
                existing_staff_permission=target.staff_permission,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_moderator_cannot_manage_staff(self):
        actor = build_staff_user(1, StaffRole.MODERATOR, can_manage_moderators=False)
        target = SimpleNamespace(id=2, username="mod", staff_permission=None)

        with self.assertRaises(HTTPException) as ctx:
            enforce_staff_assignment_permissions(
                actor,
                target_user=target,
                desired_role=StaffRole.MODERATOR,
                existing_staff_permission=None,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_self_escalation_is_blocked(self):
        actor = build_staff_user(1, StaffRole.ADMIN, can_manage_moderators=True)

        with self.assertRaises(HTTPException) as ctx:
            enforce_staff_assignment_permissions(
                actor,
                target_user=actor,
                desired_role=StaffRole.MODERATOR,
                existing_staff_permission=actor.staff_permission,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_moderator_quota_is_enforced(self):
        actor = build_staff_user(
            1,
            StaffRole.MODERATOR,
            can_create_invites=True,
            invite_quota_monthly=2,
        )

        with self.assertRaises(HTTPException) as ctx:
            ensure_staff_invite_creation_allowed(actor, invites_created_this_month=2)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("quota", ctx.exception.detail.lower())

    def test_moderator_can_create_invite_with_remaining_quota(self):
        actor = build_staff_user(
            1,
            StaffRole.MODERATOR,
            can_create_invites=True,
            invite_quota_monthly=2,
        )

        ensure_staff_invite_creation_allowed(actor, invites_created_this_month=1)

    def test_admin_invite_creation_is_not_quota_limited(self):
        actor = build_staff_user(
            1,
            StaffRole.ADMIN,
            can_create_invites=True,
            invite_quota_monthly=None,
        )

        ensure_staff_invite_creation_allowed(actor, invites_created_this_month=999)

    def test_moderator_without_invite_permission_is_denied(self):
        actor = build_staff_user(
            1,
            StaffRole.MODERATOR,
            can_create_invites=False,
            invite_quota_monthly=10,
        )

        with self.assertRaises(HTTPException) as ctx:
            ensure_staff_invite_creation_allowed(actor, invites_created_this_month=0)

        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_moderate_super_admin(self):
        actor = build_staff_user(1, StaffRole.ADMIN, can_manage_users=True)
        target = build_staff_user(2, StaffRole.SUPER_ADMIN, can_manage_users=True)

        with self.assertRaises(HTTPException) as ctx:
            enforce_staff_moderation_target(actor, target)

        self.assertEqual(ctx.exception.status_code, 403)

    def test_moderator_cannot_suspend_or_ban_without_explicit_permission(self):
        actor = build_staff_user(1, StaffRole.MODERATOR, can_suspend_users=False, can_ban_users=False)

        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_SUSPEND))
        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_BAN))

    def test_capability_maps_to_staff_permissions(self):
        actor = build_staff_user(1, StaffRole.MODERATOR, can_moderate_posts=True, can_view_moderation_queue=True)

        self.assertTrue(staff_has_capability(actor, Capability.MODERATION_POST_HIDE))
        self.assertTrue(staff_has_capability(actor, Capability.MODERATION_SIGNAL_READ))
        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_BAN))

    def test_legacy_admin_flags_are_derived_from_staff_permissions_only(self):
        actor = build_staff_user(1, StaffRole.SUPER_ADMIN, can_manage_moderators=True)

        self.assertEqual(derive_admin_response_flags(actor), (True, "super_admin"))
        self.assertTrue(staff_session_requires_security_key(actor))

    def test_security_key_requirement_denies_legacy_admin_without_staff_permissions(self):
        actor = SimpleNamespace(
            id=1,
            username="legacy-admin",
            staff_permission=None,
        )

        self.assertEqual(derive_admin_response_flags(actor), (False, None))
        self.assertFalse(staff_session_requires_security_key(actor))

    def test_legacy_is_admin_without_staff_permissions_is_denied(self):
        actor = SimpleNamespace(
            id=1,
            username="legacy-admin",
            staff_permission=None,
        )

        self.assertFalse(staff_has_capability(actor, Capability.ROLE_CHANGE))
        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_BAN))

    def test_legacy_admin_role_without_staff_permissions_is_denied(self):
        for legacy_role in ("super_admin", "moderator"):
            actor = SimpleNamespace(
                id=1,
                username=f"legacy-{legacy_role}",
                staff_permission=None,
            )

            self.assertFalse(staff_has_capability(actor, Capability.ROLE_CHANGE))
            self.assertFalse(staff_has_capability(actor, Capability.MODERATION_SUSPEND))

    def test_moderator_cannot_gain_authority_from_legacy_admin_fields(self):
        actor = build_staff_user(
            1,
            StaffRole.MODERATOR,
            can_view_moderation_queue=True,
            can_moderate_posts=True,
        )

        self.assertFalse(staff_has_capability(actor, Capability.ROLE_CHANGE))
        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_BAN))
        self.assertFalse(staff_has_capability(actor, Capability.MODERATION_SUSPEND))

    def test_invite_count_uses_utc_calendar_month_boundaries(self):
        class _FakeScalarResult:
            def scalar(self):
                return 3

        class _FakeDB:
            def __init__(self):
                self.statement = None

            async def execute(self, statement):
                self.statement = statement
                return _FakeScalarResult()

        fake_db = _FakeDB()
        frozen_now = datetime(2026, 4, 7, 12, 30, 0)

        with patch("app.services.staff_permissions.datetime") as datetime_mock:
            datetime_mock.now.return_value = frozen_now
            datetime_mock.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            count = __import__("asyncio").run(count_staff_invites_created_this_month(fake_db, actor_user_id=99))

        self.assertEqual(count, 3)
        compiled = str(
            fake_db.statement.compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("invite_codes.created_by_id = 99", compiled)
        self.assertIn("invite_codes.created_at >= '2026-04-01 00:00:00'", compiled)
        self.assertIn("invite_codes.created_at < '2026-05-01 00:00:00'", compiled)


if __name__ == "__main__":
    unittest.main()
