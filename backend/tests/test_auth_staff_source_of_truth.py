import os
import secrets
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class AuthSourceOfTruthDB:
    def __init__(self):
        self.user: User | None = None
        self.webauthn_credential: WebAuthnCredential | None = None
        self.refresh_tokens: list[RefreshToken] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is User:
            return _ScalarResult(self.user)
        if entity is WebAuthnCredential:
            return _ScalarResult(self.webauthn_credential)
        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        if isinstance(instance, RefreshToken):
            self.refresh_tokens.append(instance)

    async def flush(self):
        for index, token in enumerate(self.refresh_tokens, start=1):
            if token.id is None:
                token.id = index

    async def commit(self):
        return None


def build_user(user_id: int, username: str) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        password_hash=get_password_hash("Str0ng!Pass1"),
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
    )


class AuthStaffSourceOfTruthTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.db = AuthSourceOfTruthDB()

        async def override_db():
            yield self.db

        async def _noop_rate_limit(*args, **kwargs):
            return None

        app.dependency_overrides[get_db] = override_db
        self.rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", _noop_rate_limit)
        self.rate_limit_patch.start()
        self.audit_patch = patch("app.api.routes.auth.write_audit_log", new=AsyncMock())
        self.audit_patch.start()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.rate_limit_patch.stop()
        self.audit_patch.stop()

    def _client(self) -> TestClient:
        return TestClient(app, base_url="http://localhost")

    def test_login_requires_security_key_from_staff_permissions_even_when_legacy_columns_are_false(self):
        user = build_user(1, "staffer")
        user.staff_permission = StaffPermission(id=11, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        self.db.user = user
        self.db.webauthn_credential = None

        response = self._client().post("/api/auth/login", json={"username": user.username, "password": "Str0ng!Pass1"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin accounts require a security key. Register one first.")

    def test_login_does_not_require_security_key_from_legacy_admin_columns_alone(self):
        user = build_user(2, "legacyonly")
        user.staff_permission = None
        self.db.user = user
        self.db.webauthn_credential = None

        token_payload = {}

        def fake_create_access_token(*, data):
            token_payload.update(data)
            return "access-token"

        with patch("app.api.routes.auth.create_access_token", side_effect=fake_create_access_token):
            response = self._client().post("/api/auth/login", json={"username": user.username, "password": "Str0ng!Pass1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["access_token"], "access-token")
        self.assertNotIn("is_admin", token_payload)
        self.assertNotIn("admin_role", token_payload)

    def test_login_with_webauthn_credential_returns_202_mfa_required_not_500(self):
        user = build_user(3, "mfauser")
        user.staff_permission = None
        self.db.user = user
        self.db.webauthn_credential = WebAuthnCredential(
            id=31,
            user_id=user.id,
            credential_id=b"cred-3",
            public_key=b"public-key",
            sign_count=1,
            name="Laptop Key",
            created_at=datetime.utcnow(),
        )

        with patch("app.api.routes.auth.create_mfa_session_token", new=AsyncMock(return_value="mfa-token")):
            response = self._client().post(
                "/api/auth/login",
                json={"username": user.username, "password": "Str0ng!Pass1"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {"mfa_required": True, "mfa_session_token": "mfa-token"},
        )

    def test_admin_recovery_token_can_be_issued_for_configured_staff_without_webauthn(self):
        user = build_user(4, "recoverable-admin")
        user.staff_permission = StaffPermission(id=12, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        self.db.user = user
        self.db.webauthn_credential = None

        with patch.object(
            __import__("app.api.routes.auth", fromlist=["settings"]).settings,
            "ENABLE_ADMIN_WEBAUTHN_RECOVERY",
            True,
        ), patch.object(
            __import__("app.api.routes.auth", fromlist=["settings"]).settings,
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
            user.email,
        ), patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(return_value="recovery-token"),
        ):
            response = self._client().post(
                "/api/auth/admin-recovery/webauthn-token",
                json={"username": user.email, "password": "Str0ng!Pass1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recovery_token"], "recovery-token")

    def test_admin_recovery_token_denies_non_staff_accounts(self):
        user = build_user(5, "plainuser")
        user.staff_permission = None
        self.db.user = user
        self.db.webauthn_credential = None

        with patch.object(
            __import__("app.api.routes.auth", fromlist=["settings"]).settings,
            "ENABLE_ADMIN_WEBAUTHN_RECOVERY",
            True,
        ), patch.object(
            __import__("app.api.routes.auth", fromlist=["settings"]).settings,
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
            user.email,
        ), patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(return_value="recovery-token"),
        ) as create_recovery_token:
            response = self._client().post(
                "/api/auth/admin-recovery/webauthn-token",
                json={"username": user.email, "password": "Str0ng!Pass1"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin WebAuthn recovery is not available for this account.")
        create_recovery_token.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
