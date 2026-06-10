import os
import secrets
import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

if "jwt" not in sys.modules:
    jwt_stub = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    jwt_stub.PyJWTError = _PyJWTError
    jwt_stub.decode = lambda *args, **kwargs: {}
    sys.modules["jwt"] = jwt_stub

from app.api.deps import get_db, require_admin_session
from app.main import app
from app.models.invite import InviteCode
from app.models.moderation_signal import ModerationDetectionStatus, ModerationReviewStatus, ModerationSignal, ModerationSurface
from app.models.post import Post, PostModerationStatus
from app.models.refresh_token import RefreshToken
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus


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
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
    )
    actor.staff_permission = staff_permission
    staff_permission.user = actor
    return actor


def build_target_user(user_id: int, username: str = "target") -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        password_hash="hash",
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalar(self):
        return self._value


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class FakePhase1DB:
    def __init__(self):
        self.target_user = None
        self.staff_permission = None
        self.invite_count = 0
        self.invites = []
        self.signal = None
        self.post = None

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        statement_text = str(statement)
        if entity is User:
            return _ScalarResult(self.target_user)
        if entity is StaffPermission:
            return _ScalarResult(self.staff_permission)
        if entity is InviteCode:
            if "count(" in statement_text.lower():
                return _ScalarResult(self.invite_count)
            return _ScalarResult(None)
        if entity is ModerationSignal:
            return _ScalarResult(self.signal)
        if entity is Post:
            return _ScalarResult(self.post)
        if entity is RefreshToken:
            return _ListResult([])
        return _ScalarResult(self.invite_count)

    def add(self, instance):
        if isinstance(instance, StaffPermission):
            self.staff_permission = instance
        elif isinstance(instance, InviteCode):
            self.invites.append(instance)

    async def flush(self):
        if self.staff_permission is not None and self.staff_permission.id is None:
            self.staff_permission.id = 501
        if self.staff_permission is not None and self.staff_permission.created_at is None:
            self.staff_permission.created_at = datetime.utcnow()
        if self.staff_permission is not None and self.staff_permission.updated_at is None:
            self.staff_permission.updated_at = datetime.utcnow()
        if self.staff_permission is not None and self.staff_permission.updated_by_user is None and self.target_user is not None:
            self.staff_permission.user = self.target_user
        if self.invites and self.invites[-1].id is None:
            self.invites[-1].id = 701
        if self.invites and self.invites[-1].created_at is None:
            self.invites[-1].created_at = datetime.utcnow()

    async def commit(self):
        return None

    async def refresh(self, instance):
        return None

    async def delete(self, instance):
        if instance is self.staff_permission:
            self.staff_permission = None


class StaffPhase1ApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    def _build_client(self, db: FakePhase1DB, actor: User) -> TestClient:
        async def override_db():
            yield db

        async def override_staff():
            return actor

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin_session] = override_staff
        return TestClient(app, base_url="http://localhost")

    def _build_db_only_client(self, db: FakePhase1DB) -> TestClient:
        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        return TestClient(app, base_url="http://localhost")

    def test_staff_create_rejects_unknown_permission_field(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(22, "candidate")
        actor = build_staff_actor(1, StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        client = self._build_client(db, actor)

        response = client.post(
            "/api/admin/staff",
            json={
                "username": "candidate",
                "role": "moderator",
                "permissions": {
                    "can_create_invites": True,
                    "dangerous_field": True,
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("dangerous_field", response.text)

    def test_admin_cannot_create_super_admin_via_route(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(22, "candidate")
        actor = build_staff_actor(1, StaffRole.ADMIN, can_manage_moderators=True)
        client = self._build_client(db, actor)

        response = client.post(
            "/api/admin/staff",
            json={
                "username": "candidate",
                "role": "super_admin",
                "permissions": {
                    "can_create_invites": True,
                    "invite_quota_monthly": 0,
                    "can_view_moderation_queue": True,
                    "can_moderate_posts": True,
                    "can_manage_invites": True,
                    "can_manage_users": True,
                    "can_suspend_users": True,
                    "can_ban_users": True,
                    "can_manage_moderators": True,
                },
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_create_update_and_delete_staff_emit_phase1_audit_events(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(22, "candidate")
        actor = build_staff_actor(1, StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin_staff.write_audit_log", audit_mock):
            create_response = client.post(
                "/api/admin/staff",
                json={
                    "username": "candidate",
                    "role": "moderator",
                    "permissions": {
                        "can_create_invites": True,
                        "invite_quota_monthly": 5,
                        "can_view_moderation_queue": True,
                        "can_moderate_posts": True,
                        "can_manage_invites": False,
                        "can_manage_users": False,
                        "can_suspend_users": False,
                        "can_ban_users": False,
                        "can_manage_moderators": False,
                    },
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_call = audit_mock.await_args_list[-1].kwargs
            self.assertEqual(create_call["action"], "moderator_added")
            self.assertEqual(create_call["target_id"], 22)
            self.assertEqual(create_call["after"]["staff_permissions"]["invite_quota_monthly"], 5)

            db.staff_permission.updated_by_user = actor
            update_response = client.put(
                f"/api/admin/staff/{db.staff_permission.id}",
                json={
                    "role": "moderator",
                    "reason": "tune quota",
                    "permissions": {
                        "can_create_invites": True,
                        "invite_quota_monthly": 7,
                        "can_view_moderation_queue": True,
                        "can_moderate_posts": True,
                        "can_manage_invites": False,
                        "can_manage_users": False,
                        "can_suspend_users": False,
                        "can_ban_users": False,
                        "can_manage_moderators": False,
                    },
                },
            )
            self.assertEqual(update_response.status_code, 200)
            update_call = audit_mock.await_args_list[-1].kwargs
            self.assertEqual(update_call["action"], "staff_permissions_updated")
            self.assertEqual(update_call["before"]["invite_quota_monthly"], 5)
            self.assertEqual(update_call["after"]["invite_quota_monthly"], 7)

            delete_response = client.request(
                "DELETE",
                f"/api/admin/staff/{db.staff_permission.id}",
                json={"reason": "remove access"},
            )
            self.assertEqual(delete_response.status_code, 204)
            delete_call = audit_mock.await_args_list[-1].kwargs
            self.assertEqual(delete_call["action"], "moderator_removed")
            self.assertEqual(delete_call["before"]["invite_quota_monthly"], 7)

    def test_moderator_invite_create_denied_without_permission(self):
        db = FakePhase1DB()
        actor = build_staff_actor(1, StaffRole.MODERATOR, can_create_invites=False, invite_quota_monthly=5)
        client = self._build_client(db, actor)

        response = client.post("/api/invite/create", json={})

        self.assertEqual(response.status_code, 403)

    def test_moderator_invite_quota_is_enforced_server_side(self):
        db = FakePhase1DB()
        db.invite_count = 2
        actor = build_staff_actor(1, StaffRole.MODERATOR, can_create_invites=True, invite_quota_monthly=2)
        client = self._build_client(db, actor)

        with patch("app.api.routes.invite.enforce_rate_limits", AsyncMock()):
            response = client.post("/api/invite/create", json={})

        self.assertEqual(response.status_code, 403)
        self.assertIn("Monthly invite quota exceeded", response.text)

    def test_admin_invite_create_bypasses_quota_and_writes_audit(self):
        db = FakePhase1DB()
        actor = build_staff_actor(1, StaffRole.ADMIN, can_create_invites=True, can_manage_invites=True, invite_quota_monthly=None)
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.invite.enforce_rate_limits", AsyncMock()), patch(
            "app.api.routes.invite.write_audit_log",
            audit_mock,
        ), patch("app.api.routes.invite.generate_invite_code", return_value="A" * 32):
            response = client.post("/api/invite/create", json={"internal_note": "phase1"})

        self.assertEqual(response.status_code, 201)
        create_call = audit_mock.await_args_list[0].kwargs
        self.assertEqual(create_call["action"], "invite_created_by_staff")
        self.assertEqual(create_call["target_type"], "invite")
        self.assertEqual(create_call["after"]["created_by_user_id"], actor.id)
        self.assertEqual(create_call["after"]["invites_created_this_month"], 1)
        self.assertIsNone(create_call["after"]["invite_quota_monthly"])

    def test_admin_session_reports_current_capabilities(self):
        db = FakePhase1DB()
        actor = build_staff_actor(
            1,
            StaffRole.ADMIN,
            can_create_invites=True,
            can_manage_invites=True,
            can_manage_users=True,
            can_suspend_users=True,
            can_ban_users=False,
            can_view_moderation_queue=True,
            can_moderate_posts=True,
            can_manage_moderators=False,
        )
        client = self._build_client(db, actor)

        response = client.get("/api/admin/session")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["role"], "admin")
        self.assertTrue(payload["permissions"]["can_create_invites"])
        self.assertTrue(payload["capabilities"]["can_create_invites"])
        self.assertTrue(payload["capabilities"]["can_assign_invites"])
        self.assertTrue(payload["capabilities"]["can_manage_campaigns"])
        self.assertTrue(payload["capabilities"]["can_manage_users"])
        self.assertTrue(payload["capabilities"]["can_suspend_users"])
        self.assertFalse(payload["capabilities"]["can_ban_users"])
        self.assertTrue(payload["capabilities"]["can_view_moderation_queue"])
        self.assertTrue(payload["capabilities"]["can_moderate_posts"])
        self.assertFalse(payload["capabilities"]["can_manage_moderators"])

    def test_freeze_route_writes_moderation_action_taken(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(33, "freezee")
        actor = build_staff_actor(1, StaffRole.ADMIN, can_manage_users=True)
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.enforce_rate_limits", AsyncMock()), patch(
            "app.api.routes.admin.write_audit_log",
            audit_mock,
        ):
            response = client.post("/api/admin/users/33/freeze", json={"reason": "policy"})

        self.assertEqual(response.status_code, 200)
        audit_call = audit_mock.await_args.kwargs
        self.assertEqual(audit_call["action"], "moderation_action_taken")
        self.assertEqual(audit_call["after"]["action"], "freeze_user")

    def test_moderation_queue_suspend_writes_user_and_signal_audits(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(44, "queued-user")
        db.signal = ModerationSignal(
            id=91,
            user_id=44,
            surface_type=ModerationSurface.POST_TEXT,
            detection_status=ModerationDetectionStatus.SUSPICIOUS,
            review_status=ModerationReviewStatus.OPEN,
        )
        actor = build_staff_actor(1, StaffRole.ADMIN, can_suspend_users=True)
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.enforce_rate_limits", AsyncMock()), patch(
            "app.api.routes.admin.write_audit_log",
            audit_mock,
        ):
            response = client.post(
                "/api/admin/moderation/queue/91/action",
                json={"action": "suspend_user", "note": "queue policy"},
            )

        self.assertEqual(response.status_code, 200)
        actions = [call.kwargs["action"] for call in audit_mock.await_args_list]
        self.assertIn("user_suspended", actions)
        self.assertIn("moderation_action_taken", actions)

    def test_require_admin_session_rejects_legacy_admin_without_staff_permissions(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(55, "legacy-only")
        client = self._build_db_only_client(db)

        with patch(
            "app.api.deps.jwt.decode",
            return_value={"sub": "55", "username": "legacy-only", "admin_role": "super_admin", "exp": 9999999999},
        ):
            response = client.get("/api/admin/search?q=ab", headers={"Authorization": "Bearer legacy-token"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("Admin session required", response.text)

    def test_auth_me_ignores_crafted_legacy_admin_role_without_staff_permissions(self):
        db = FakePhase1DB()
        db.target_user = build_target_user(66, "crafted-claims")
        client = self._build_db_only_client(db)

        with patch(
            "app.api.deps.jwt.decode",
            return_value={"sub": "66", "username": "crafted-claims", "admin_role": "super_admin", "exp": 9999999999},
        ):
            response = client.get("/api/auth/me", headers={"Authorization": "Bearer crafted-token"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["is_admin"])
        self.assertIsNone(body["admin_role"])

    def test_auth_me_derives_admin_flags_from_staff_permissions_when_legacy_columns_disagree(self):
        db = FakePhase1DB()
        db.target_user = build_staff_actor(67, StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        client = self._build_db_only_client(db)

        with patch(
            "app.api.deps.jwt.decode",
            return_value={"sub": "67", "username": "staff67", "admin_role": None, "exp": 9999999999},
        ):
            response = client.get("/api/auth/me", headers={"Authorization": "Bearer derived-token"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["is_admin"])
        self.assertEqual(body["admin_role"], "super_admin")


if __name__ == "__main__":
    unittest.main()
