import os
import secrets
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db, require_admin_session
from app.core.security import get_password_hash
from app.main import app
from app.models.admin_password_reset_token import AdminPasswordResetToken
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.services.admin_security import hash_admin_password_reset_secret


def build_staff_actor(user_id: int, role: StaffRole, **overrides) -> User:
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
        password_hash=get_password_hash("Str0ng!Pass"),
        is_active=True,
        status=UserStatus.ACTIVE,
    )
    actor.staff_permission = staff_permission
    staff_permission.user = actor
    return actor


def build_target_user(user_id: int, username: str = "target") -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        password_hash=get_password_hash("An0ther!Pass"),
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        must_change_password=False,
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


class FakeSecureAdminDB:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.reset_tokens: list[AdminPasswordResetToken] = []
        self.public_reset_tokens: list[PasswordResetToken] = []
        self.refresh_tokens: list[RefreshToken] = []
        self._next_reset_token_id = 1
        self._next_public_reset_token_id = 1
        self._next_refresh_id = 1

    async def execute(self, statement):
        # Handle UPDATE statements (no column_descriptions)
        if not hasattr(statement, 'column_descriptions'):
            return await self._execute_update(statement)
        entity = statement.column_descriptions[0].get("entity")
        params = statement.compile().params
        statement_text = str(statement)

        if entity is User:
            user_id = next((value for key, value in params.items() if key.endswith("id_1") or key == "id_1"), None)
            if user_id is not None:
                return _ScalarResult(self.users.get(int(user_id)))

            identifier = next((value for key, value in params.items() if "username" in key or "email" in key), None)
            if identifier is not None:
                for user in self.users.values():
                    if user.username == identifier or user.email == identifier:
                        return _ScalarResult(user)
            return _ScalarResult(None)

        if entity is AdminPasswordResetToken:
            if any("token_hash" in key for key in params):
                token_hash = next(value for key, value in params.items() if "token_hash" in key)
                token = next((item for item in self.reset_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            values = [
                item
                for item in self.reset_tokens
                if user_id is None or item.user_id == int(user_id)
            ]
            if "used_at IS NULL" in statement_text:
                values = [item for item in values if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                values = [item for item in values if item.revoked_at is None]
            return _ListResult(values)

        if entity is PasswordResetToken:
            if any("token_hash" in key for key in params):
                token_hash = next(value for key, value in params.items() if "token_hash" in key)
                token = next((item for item in self.public_reset_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            values = [
                item
                for item in self.public_reset_tokens
                if user_id is None or item.user_id == int(user_id)
            ]
            if "used_at IS NULL" in statement_text:
                values = [item for item in values if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                values = [item for item in values if item.revoked_at is None]
            return _ListResult(values)

        if entity is RefreshToken:
            if any("token_hash" in key for key in params):
                token_hash = next(value for key, value in params.items() if "token_hash" in key)
                token = next((item for item in self.refresh_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            values = [
                item
                for item in self.refresh_tokens
                if user_id is None or item.user_id == int(user_id)
            ]
            if "refresh_tokens.revoked = false" in statement_text.lower():
                values = [item for item in values if not item.revoked]
            return _ListResult(values)

        raise AssertionError(f"Unexpected entity {entity}")

    async def _execute_update(self, statement):
        from datetime import datetime, timezone
        table_name = statement.table.name
        params = statement.compile().params
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)

        def _normalize(dt):
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        if table_name == "admin_password_reset_tokens":
            token_id = next((v for k, v in params.items() if k.startswith("id_")), None)
            used_at = next((v for k, v in params.items() if "used_at" in k), now)
            token = next((t for t in self.reset_tokens if t.id == token_id), None)
            expires = _normalize(token.expires_at) if token else None
            if token and token.used_at is None and token.revoked_at is None and expires is not None and expires >= now_naive:
                token.used_at = used_at
                return _ScalarResult(token.id)
            return _ScalarResult(None)

        if table_name == "password_reset_tokens":
            token_id = next((v for k, v in params.items() if k.startswith("id_")), None)
            used_at = next((v for k, v in params.items() if "used_at" in k), now)
            token = next((t for t in self.public_reset_tokens if t.id == token_id), None)
            if token and token.used_at is None and token.revoked_at is None:
                token.used_at = used_at
                return _ScalarResult(token.id)
            return _ScalarResult(None)

        if table_name == "refresh_tokens":
            revoked_at = next((v for k, v in params.items() if "revoked_at" in k), now)
            for token in self.refresh_tokens:
                if not token.revoked:
                    token.revoked = True
                    token.revoked_at = revoked_at
            return _ScalarResult(len(self.refresh_tokens))

        raise AssertionError(f"Unexpected UPDATE on table '{table_name}'")

    def add(self, instance):
        if isinstance(instance, AdminPasswordResetToken):
            if instance.id is None:
                instance.id = self._next_reset_token_id
                self._next_reset_token_id += 1
            self.reset_tokens.append(instance)
        elif isinstance(instance, PasswordResetToken):
            if instance.id is None:
                instance.id = self._next_public_reset_token_id
                self._next_public_reset_token_id += 1
            self.public_reset_tokens.append(instance)
        elif isinstance(instance, RefreshToken):
            if instance.id is None:
                instance.id = self._next_refresh_id
                self._next_refresh_id += 1
            self.refresh_tokens.append(instance)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class AdminSecureActionsPhase2Tests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        async def _noop_rate_limit(*args, **kwargs):
            return None

        self._rate_limit_patch = patch("app.api.routes.admin.enforce_rate_limits", _noop_rate_limit)
        self._auth_rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", _noop_rate_limit)
        self._rate_limit_patch.start()
        self._auth_rate_limit_patch.start()

    def tearDown(self):
        app.dependency_overrides.clear()
        self._rate_limit_patch.stop()
        self._auth_rate_limit_patch.stop()

    def _build_client(self, db: FakeSecureAdminDB, actor: User | None = None) -> TestClient:
        async def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        if actor is not None:
            async def override_staff():
                return actor

            app.dependency_overrides[require_admin_session] = override_staff
        return TestClient(app, base_url="http://localhost")

    def test_unauthorized_actor_gets_403_for_force_password_reset(self):
        db = FakeSecureAdminDB()
        actor = build_target_user(1, "plain-user")
        target = build_target_user(2, "target-user")
        db.users[target.id] = target
        client = self._build_client(db, actor)

        response = client.post("/api/admin/users/2/force-password-reset", json={"reason": "compromise"})

        self.assertEqual(response.status_code, 403)

    def test_moderator_cannot_use_phase2_actions_by_default(self):
        db = FakeSecureAdminDB()
        actor = build_staff_actor(1, StaffRole.MODERATOR)
        target = build_target_user(2, "target-user")
        db.users[target.id] = target
        client = self._build_client(db, actor)

        reset_response = client.post("/api/admin/users/2/force-password-reset", json={"reason": "compromise"})
        revoke_response = client.post("/api/admin/users/2/revoke-sessions", json={"reason": "compromise"})

        self.assertEqual(reset_response.status_code, 403)
        self.assertEqual(revoke_response.status_code, 403)

    def test_equal_or_higher_role_target_protection_still_holds(self):
        db = FakeSecureAdminDB()
        actor = build_staff_actor(1, StaffRole.ADMIN, can_reset_passwords=True, can_revoke_sessions=True)
        target = build_staff_actor(2, StaffRole.ADMIN, can_manage_users=True)
        db.users[target.id] = target
        client = self._build_client(db, actor)

        reset_response = client.post("/api/admin/users/2/force-password-reset", json={"reason": "compromise"})
        revoke_response = client.post("/api/admin/users/2/revoke-sessions", json={"reason": "compromise"})

        self.assertEqual(reset_response.status_code, 403)
        self.assertEqual(revoke_response.status_code, 403)

    def test_force_password_reset_writes_audit_without_plaintext_secret(self):
        db = FakeSecureAdminDB()
        actor = build_staff_actor(1, StaffRole.SUPER_ADMIN, can_reset_passwords=True)
        target = build_target_user(2, "target-user")
        db.users[target.id] = target
        stale_token = AdminPasswordResetToken(
            id=9,
            user_id=target.id,
            token_hash="stale-hash",
            issued_by_user_id=actor.id,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        )
        db.reset_tokens.append(stale_token)
        db.refresh_tokens.extend(
            [
                RefreshToken(id=1, user_id=target.id, token_hash="active-a", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
                RefreshToken(id=2, user_id=target.id, token_hash="active-b", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
            ]
        )
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.write_audit_log", audit_mock):
            response = client.post("/api/admin/users/2/force-password-reset", json={"reason": "Account compromise"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["reset_token"])
        self.assertTrue(target.must_change_password)
        self.assertEqual(payload["invalidated_reset_artifacts"], 1)
        self.assertEqual(payload["revoked_session_count"], 2)
        self.assertTrue(all(token.revoked for token in db.refresh_tokens))
        self.assertNotEqual(db.reset_tokens[-1].token_hash, payload["reset_token"])
        self.assertEqual(len(audit_mock.await_args_list), 2)
        for call in audit_mock.await_args_list:
            kwargs = call.kwargs
            self.assertNotIn(payload["reset_token"], str(kwargs))
            self.assertNotIn("token_hash", str(kwargs))
        self.assertEqual(audit_mock.await_args_list[0].kwargs["action"], "password_reset_forced")
        self.assertEqual(audit_mock.await_args_list[0].kwargs["after"]["revoked_session_count"], 2)
        self.assertEqual(audit_mock.await_args_list[1].kwargs["action"], "password_reset_token_issued")

    def test_revoke_sessions_writes_audit_and_revokes_active_refresh_tokens(self):
        db = FakeSecureAdminDB()
        actor = build_staff_actor(1, StaffRole.SUPER_ADMIN, can_revoke_sessions=True)
        target = build_target_user(2, "target-user")
        db.users[target.id] = target
        db.refresh_tokens.extend(
            [
                RefreshToken(id=1, user_id=target.id, token_hash="a", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
                RefreshToken(id=2, user_id=target.id, token_hash="b", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
                RefreshToken(id=3, user_id=target.id, token_hash="c", expires_at=datetime.utcnow() + timedelta(days=7), revoked=True),
            ]
        )
        client = self._build_client(db, actor)

        audit_mock = AsyncMock()
        with patch("app.api.routes.admin.write_audit_log", audit_mock):
            response = client.post("/api/admin/users/2/revoke-sessions", json={"reason": "Contain the account"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked_session_count"], 2)
        self.assertTrue(db.refresh_tokens[0].revoked)
        self.assertTrue(db.refresh_tokens[1].revoked)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "sessions_revoked")
        self.assertEqual(audit_mock.await_args.kwargs["after"]["scope"], "all_active_refresh_tokens")

    def test_admin_reset_token_expiry_is_enforced(self):
        db = FakeSecureAdminDB()
        target = build_target_user(2, "target-user")
        db.users[target.id] = target
        secret = "expired-secret-token-value-0123456789"
        db.reset_tokens.append(
            AdminPasswordResetToken(
                id=1,
                user_id=target.id,
                token_hash=hash_admin_password_reset_secret(secret),
                issued_by_user_id=99,
                expires_at=datetime.utcnow() - timedelta(minutes=1),
            )
        )
        client = self._build_client(db)

        response = client.post(
            "/api/auth/password-reset/complete",
            json={"token": secret, "new_password": "N3w!Password"},
        )

        self.assertEqual(response.status_code, 400)

    def test_password_reset_completion_clears_flag_and_revokes_sessions(self):
        db = FakeSecureAdminDB()
        target = build_target_user(2, "target-user")
        target.must_change_password = True
        db.users[target.id] = target
        secret = "usable-secret-token-value-0123456789"
        token = AdminPasswordResetToken(
            id=1,
            user_id=target.id,
            token_hash=hash_admin_password_reset_secret(secret),
            issued_by_user_id=99,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.reset_tokens.append(token)
        db.refresh_tokens.extend(
            [
                RefreshToken(id=1, user_id=target.id, token_hash="a", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
                RefreshToken(id=2, user_id=target.id, token_hash="b", expires_at=datetime.utcnow() + timedelta(days=7), revoked=False),
            ]
        )
        client = self._build_client(db)

        audit_mock = AsyncMock()
        with patch("app.api.routes.auth.write_audit_log", audit_mock):
            response = client.post(
                "/api/auth/password-reset/complete",
                json={"token": secret, "new_password": "N3w!Password"},
            )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(target.must_change_password)
        self.assertIsNotNone(token.used_at)
        self.assertTrue(all(refresh.revoked for refresh in db.refresh_tokens))
        self.assertEqual(audit_mock.await_args.kwargs["action"], "password_reset_completed")

    def test_admin_reset_completion_revokes_public_reset_tokens_too(self):
        db = FakeSecureAdminDB()
        target = build_target_user(2, "target-user")
        target.must_change_password = True
        db.users[target.id] = target
        admin_secret = "usable-secret-token-value-0123456789"
        public_secret = "public-secret-token-value-0123456789"
        token = AdminPasswordResetToken(
            id=1,
            user_id=target.id,
            token_hash=hash_admin_password_reset_secret(admin_secret),
            issued_by_user_id=99,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.reset_tokens.append(token)
        db.public_reset_tokens.append(
            PasswordResetToken(
                id=2,
                user_id=target.id,
                email=target.email,
                token_hash=public_secret,
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
        )
        client = self._build_client(db)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            response = client.post(
                "/api/auth/password-reset/complete",
                json={"token": admin_secret, "new_password": "N3w!Password"},
            )

        self.assertEqual(response.status_code, 204)
        self.assertIsNotNone(db.public_reset_tokens[0].revoked_at)

    def test_login_is_blocked_when_must_change_password_is_set(self):
        db = FakeSecureAdminDB()
        target = build_target_user(2, "target-user")
        target.password_hash = get_password_hash("N3w!Password")
        target.must_change_password = True
        db.users[target.id] = target
        client = self._build_client(db)

        audit_mock = AsyncMock()
        with patch("app.api.routes.auth.write_audit_log", audit_mock):
            response = client.post("/api/auth/login", json={"username": "target-user", "password": "N3w!Password"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "login.password_reset_required")


if __name__ == "__main__":
    unittest.main()
