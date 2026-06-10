import os
import secrets
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api import deps
from app.api.deps import get_db, require_admin_session
from app.main import app
from app.models.invite import InviteCode, InviteType
from app.models.invite_campaign import InviteCampaign
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.services.invite_campaigns import CampaignRuleViolation


def build_staff_actor(user_id: int, role: StaffRole, **overrides):
    permission_defaults = {
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
    permission_defaults.update(overrides)
    staff_permission = StaffPermission(id=1000 + user_id, user_id=user_id, role=role, **permission_defaults)
    actor = User(
        id=user_id,
        username=f"staff{user_id}",
        email=f"staff{user_id}@example.com",
        password_hash="hash",
        is_active=True,
        status=UserStatus.ACTIVE,
    )
    actor.staff_permission = staff_permission
    staff_permission.user = actor
    return actor


def build_user(user_id: int, username: str) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        password_hash="hash",
        is_active=True,
        status=UserStatus.ACTIVE,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _ListResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class FakeCampaignDB:
    def __init__(self):
        self.campaign = None
        self.invite = None
        self.created_campaigns = []
        self.commits = 0

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, statement):
        text = str(statement)
        if "SELECT invite_campaigns.id" in text and "WHERE invite_campaigns.slug =" in text:
            return _ScalarResult(None)
        if "invite_campaigns" in text:
            return _ScalarResult(self.campaign)
        if "FROM invite_codes" in text and "SELECT invite_codes.id" in text:
            return _ScalarResult(None)
        return _ScalarResult(None)

    def add(self, instance):
        if isinstance(instance, InviteCampaign):
            if instance.id is None:
                instance.id = 401
            self.campaign = instance
            self.created_campaigns = [instance]
        elif isinstance(instance, InviteCode):
            if instance.id is None:
                instance.id = 777
            self.invite = instance

    async def flush(self):
        if self.campaign and self.campaign.created_at is None:
            self.campaign.created_at = datetime.utcnow()
        if self.campaign and self.campaign.updated_at is None:
            self.campaign.updated_at = datetime.utcnow()

    async def commit(self):
        self.commits += 1

    async def refresh(self, instance):
        return None


class Phase3WaveCampaignApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    def _client_with_admin(self, db: FakeCampaignDB, actor: User) -> TestClient:
        async def override_db():
            yield db

        async def override_admin():
            return actor

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin_session] = override_admin
        return TestClient(app, base_url="http://localhost")

    def _client_with_user(self, db: FakeCampaignDB, actor: User) -> TestClient:
        async def override_db():
            yield db

        async def override_user():
            return actor

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[deps.get_current_interactive_user] = override_user
        return TestClient(app, base_url="http://localhost")

    def test_unauthorized_actor_gets_403_for_campaign_create(self):
        db = FakeCampaignDB()
        actor = build_staff_actor(1, StaffRole.MODERATOR, can_manage_invites=False)
        client = self._client_with_admin(db, actor)

        response = client.post(
            "/api/admin/invite-campaigns",
            json={
                "name": "Beta Wave",
                "slug": "beta-wave",
                "is_active": True,
                "per_user_invite_allowance": 1,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_authorized_actor_can_create_campaign_and_emits_audit(self):
        db = FakeCampaignDB()
        actor = build_staff_actor(1, StaffRole.ADMIN, can_manage_invites=True)
        client = self._client_with_admin(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            with patch("app.api.routes.admin.write_audit_log", audit_mock):
                response = client.post(
                    "/api/admin/invite-campaigns",
                    json={
                        "name": "Beta Wave",
                        "slug": "beta-wave",
                        "public_label": "Beta Wave",
                        "is_active": True,
                        "max_uses_total": 20,
                        "per_user_invite_allowance": 2,
                    },
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["slug"], "beta-wave")
        self.assertEqual(response.json()["per_user_invite_allowance"], 2)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "campaign_created")

    def test_authorized_actor_can_update_campaign_and_toggle_active_state(self):
        db = FakeCampaignDB()
        db.campaign = InviteCampaign(
            id=501,
            name="Beta Wave",
            slug="beta-wave",
            is_active=False,
            per_user_invite_allowance=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        actor = build_staff_actor(1, StaffRole.ADMIN, can_manage_invites=True)
        client = self._client_with_admin(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            with patch("app.api.routes.admin.write_audit_log", audit_mock):
                response = client.patch(
                    "/api/admin/invite-campaigns/501",
                    json={"is_active": True, "per_user_invite_allowance": 3},
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_active"])
        self.assertEqual(response.json()["per_user_invite_allowance"], 3)
        self.assertEqual([call.kwargs["action"] for call in audit_mock.await_args_list], ["campaign_updated", "campaign_activated"])

    def test_campaign_invite_generation_works_and_emits_audit(self):
        db = FakeCampaignDB()
        db.campaign = InviteCampaign(
            id=601,
            name="Referral Wave",
            slug="referral-wave",
            is_active=True,
            per_user_invite_allowance=2,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        actor = build_user(7, "member")
        client = self._client_with_user(db, actor)
        invite = InviteCode(
            id=888,
            code="WAVECODE123",
            invite_type=InviteType.REFERRAL,
            created_by_id=actor.id,
            generated_by_user_id=actor.id,
            assigned_to_user_id=actor.id,
            assigned_to_username=actor.username,
            campaign_id=db.campaign.id,
            max_uses=1,
            current_uses=0,
            is_active=True,
        )

        audit_mock = AsyncMock()
        with patch("app.api.routes.invites.enforce_rate_limits", new=AsyncMock()):
            with patch("app.api.routes.invites.create_campaign_invite", new=AsyncMock(return_value=(invite, {"user_generated_count": 1, "user_remaining_allowance": 1}))):
                with patch("app.api.routes.invites.write_audit_log", audit_mock):
                    response = client.post("/api/invites/campaigns/601/generate")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["campaign_id"], 601)
        self.assertEqual(response.json()["user_remaining_allowance"], 1)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "campaign_invite_generated")

    def test_over_limit_generation_is_denied_and_audited(self):
        db = FakeCampaignDB()
        db.campaign = InviteCampaign(
            id=602,
            name="Referral Wave",
            slug="referral-wave",
            is_active=True,
            per_user_invite_allowance=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        actor = build_user(8, "member")
        client = self._client_with_user(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.invites.enforce_rate_limits", new=AsyncMock()):
            with patch(
                "app.api.routes.invites.create_campaign_invite",
                new=AsyncMock(side_effect=CampaignRuleViolation("allowance_exhausted", "Denied")),
            ):
                with patch("app.api.routes.invites.write_audit_log", audit_mock):
                    response = client.post("/api/invites/campaigns/602/generate")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "campaign_invite_generation_denied")


if __name__ == "__main__":
    unittest.main()
