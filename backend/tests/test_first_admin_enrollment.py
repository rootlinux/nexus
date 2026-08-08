"""Regression coverage for the supported first-administrator enrolment path.

A privileged account cannot sign in with a password alone, and the ordinary
`/webauthn/register/begin` endpoint needs a session that such an account cannot obtain
without a passkey. `ENABLE_ADMIN_WEBAUTHN_RECOVERY` is the one supported way out of that
deadlock, and this module pins both halves of the contract:

* the documented happy path actually works end to end on a fresh install, and
* every misuse of it is refused — wrong identifier, wrong password, non-staff account,
  an account that already owns a passkey, the flag switched off, and production.
"""

import os
import secrets
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db
from app.api.routes import auth as auth_routes
from app.core.security import get_password_hash
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
ENROLLMENT_PAGE = REPO_ROOT / "web" / "src" / "app" / "auth" / "admin-enrollment" / "page.tsx"

ADMIN_PASSWORD = "Str0ng!Pass1"
DENIAL = "Admin WebAuthn recovery is not available for this account."


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class EnrollmentDB:
    """Minimal in-process stand-in: one user, optionally one passkey."""

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


def build_bootstrap_admin(username: str = "nexus-founder") -> User:
    """Mirrors what app/bootstrap.py creates: active, verified, SUPER_ADMIN, no passkey."""
    now = datetime.utcnow()
    user = User(
        id=1,
        username=username,
        email=f"{username}@nexus.local",
        password_hash=get_password_hash(ADMIN_PASSWORD),
        display_name=username,
        created_at=now,
        is_active=True,
        must_change_password=False,
        email_verified_at=now,
        status=UserStatus.ACTIVE,
    )
    user.staff_permission = StaffPermission(
        id=1,
        user_id=user.id,
        role=StaffRole.SUPER_ADMIN,
        can_manage_moderators=True,
    )
    return user


def build_passkey(user_id: int) -> WebAuthnCredential:
    return WebAuthnCredential(
        id=1,
        user_id=user_id,
        credential_id=b"credential-bytes",
        public_key=b"public-key-bytes",
        sign_count=0,
        name="Founder key",
        created_at=datetime.utcnow(),
    )


class FirstAdminEnrollmentFlowTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.db = EnrollmentDB()
        self.admin = build_bootstrap_admin()
        self.db.user = self.admin

        async def override_db():
            yield self.db

        async def _noop_rate_limit(*args, **kwargs):
            return None

        app.dependency_overrides[get_db] = override_db
        self._patches = [
            patch("app.api.routes.auth.enforce_rate_limits", _noop_rate_limit),
            patch("app.api.routes.auth.write_audit_log", new=AsyncMock()),
        ]
        for active_patch in self._patches:
            active_patch.start()

    def tearDown(self):
        app.dependency_overrides.clear()
        for active_patch in self._patches:
            active_patch.stop()

    def _client(self) -> TestClient:
        return TestClient(app, base_url="http://localhost")

    def _enrollment_enabled(self, identifier: str | None = None):
        return (
            patch.object(auth_routes.settings, "ENABLE_ADMIN_WEBAUTHN_RECOVERY", True),
            patch.object(
                auth_routes.settings,
                "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
                identifier if identifier is not None else self.admin.username,
            ),
        )

    def _request_token(self, username: str, password: str = ADMIN_PASSWORD):
        return self._client().post(
            "/api/auth/admin-recovery/webauthn-token",
            json={"username": username, "password": password},
        )

    # --- the documented happy path ------------------------------------------------

    def test_fresh_bootstrap_admin_cannot_sign_in_with_password_alone(self):
        # This is the deadlock the enrolment path exists to break. If this assertion ever
        # flips to 200, privileged MFA enforcement has regressed and the rest of this
        # module is testing the wrong thing.
        response = self._client().post(
            "/api/auth/login",
            json={"username": self.admin.username, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Admin accounts require a security key. Register one first.",
        )

    def test_enrollment_token_is_issued_to_the_configured_bootstrap_admin(self):
        env_flag, env_identifier = self._enrollment_enabled()
        with env_flag, env_identifier, patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(return_value="enrolment-token"),
        ):
            response = self._request_token(self.admin.username)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["recovery_token"], "enrolment-token")
        self.assertGreater(body["expires_in_seconds"], 0)

    def test_login_returns_an_mfa_challenge_once_the_passkey_exists(self):
        # Closes the acceptance loop: after enrolment the account authenticates through
        # the normal password -> passkey flow, with no bypass and no weakened MFA gate.
        self.db.webauthn_credential = build_passkey(self.admin.id)

        with patch(
            "app.api.routes.auth.create_mfa_session_token",
            new=AsyncMock(return_value="mfa-token"),
        ):
            response = self._client().post(
                "/api/auth/login",
                json={"username": self.admin.username, "password": ADMIN_PASSWORD},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"mfa_required": True, "mfa_session_token": "mfa-token"})

    # --- misuse -------------------------------------------------------------------

    def test_enrollment_endpoint_is_absent_when_the_flag_is_off(self):
        with patch.object(auth_routes.settings, "ENABLE_ADMIN_WEBAUTHN_RECOVERY", False):
            response = self._request_token(self.admin.username)
        self.assertEqual(response.status_code, 404)

    def test_enrollment_denies_a_username_other_than_the_configured_identifier(self):
        env_flag, env_identifier = self._enrollment_enabled(identifier="someone-else")
        with env_flag, env_identifier, patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(),
        ) as mint:
            response = self._request_token(self.admin.username)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], DENIAL)
        mint.assert_not_awaited()

    def test_enrollment_denies_a_wrong_password(self):
        env_flag, env_identifier = self._enrollment_enabled()
        with env_flag, env_identifier, patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(),
        ) as mint:
            response = self._request_token(self.admin.username, password="not-the-password")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], DENIAL)
        mint.assert_not_awaited()

    def test_enrollment_closes_itself_once_the_account_owns_a_passkey(self):
        # The path is one-time by construction rather than by an operator remembering to
        # turn the flag off: an account with any credential is no longer eligible.
        self.db.webauthn_credential = build_passkey(self.admin.id)
        env_flag, env_identifier = self._enrollment_enabled()
        with env_flag, env_identifier, patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(),
        ) as mint:
            response = self._request_token(self.admin.username)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], DENIAL)
        mint.assert_not_awaited()

    def test_enrollment_denies_a_non_staff_account_even_when_it_is_the_identifier(self):
        self.admin.staff_permission = None
        env_flag, env_identifier = self._enrollment_enabled()
        with env_flag, env_identifier, patch(
            "app.api.routes.auth.create_admin_webauthn_recovery_token",
            new=AsyncMock(),
        ) as mint:
            response = self._request_token(self.admin.username)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], DENIAL)
        mint.assert_not_awaited()


class FirstAdminEnrollmentConfigGateTests(unittest.TestCase):
    """`Settings()` decides where the enrolment path may exist at all. Fail closed."""

    @staticmethod
    def _settings_env(**overrides: str) -> dict[str, str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("ENABLE_", "ADMIN_", "BOOTSTRAP_", "APP_ENV"))
        }
        env.update(
            {
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb",
                "REDIS_URL": "redis://localhost:6379/0",
                "SECRET_KEY": secrets.token_hex(64),
                "ENABLE_ADMIN_WEBAUTHN_RECOVERY": "true",
                "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER": "nexus-founder",
            }
        )
        env.update(overrides)
        return env

    @staticmethod
    def _load_settings(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", "from app.core.config import Settings; Settings(); print('OK')"],
            cwd=BACKEND_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_enrollment_is_allowed_in_local_development(self):
        # The reason this module exists: without dev environments in the allowlist there
        # is no supported way to get a working admin on a fresh local install.
        for app_env in ("development", "dev", "local"):
            with self.subTest(app_env=app_env):
                result = self._load_settings(self._settings_env(APP_ENV=app_env))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_enrollment_is_still_allowed_in_staging_and_test(self):
        for app_env in ("staging", "stage", "test", "testing"):
            with self.subTest(app_env=app_env):
                result = self._load_settings(self._settings_env(APP_ENV=app_env))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_enrollment_is_refused_in_production(self):
        for app_env in ("production", "prod", "release"):
            with self.subTest(app_env=app_env):
                result = self._load_settings(
                    self._settings_env(
                        APP_ENV=app_env,
                        ALLOWED_HOSTS="api.nexus.example",
                        CORS_ALLOWED_ORIGINS="https://app.nexus.example",
                        API_PUBLIC_BASE_URL="https://api.nexus.example",
                        REDIS_URL="rediss://:password@redis.internal:6379/0",
                    )
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ENABLE_ADMIN_WEBAUTHN_RECOVERY", result.stderr)

    def test_enrollment_is_refused_for_an_unrecognised_environment(self):
        # Allowlist, not denylist: a typo'd or novel APP_ENV must not be assumed safe.
        result = self._load_settings(self._settings_env(APP_ENV="prodution"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENABLE_ADMIN_WEBAUTHN_RECOVERY", result.stderr)

    def test_enrollment_requires_an_explicit_identifier(self):
        result = self._load_settings(
            self._settings_env(APP_ENV="development", ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER="")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER", result.stderr)


class FirstAdminEnrollmentFrontendTests(unittest.TestCase):
    """The README points developers at a URL; keep that page wired to the real endpoints."""

    def test_enrollment_page_exists(self):
        self.assertTrue(ENROLLMENT_PAGE.exists(), f"missing {ENROLLMENT_PAGE}")

    def test_enrollment_page_drives_all_three_backend_calls(self):
        contents = ENROLLMENT_PAGE.read_text()
        for helper in (
            "requestAdminEnrollmentToken",
            "adminEnrollmentRegisterBegin",
            "adminEnrollmentRegisterComplete",
            "startRegistration",
        ):
            self.assertIn(helper, contents)

    def test_enrollment_api_helpers_target_the_documented_routes(self):
        api_client = (REPO_ROOT / "web" / "src" / "lib" / "api.ts").read_text()
        for route in (
            "/api/auth/admin-recovery/webauthn-token",
            "/api/webauthn/recovery/register/begin",
            "/api/webauthn/recovery/register/complete",
        ):
            self.assertIn(route, api_client)


if __name__ == "__main__":
    unittest.main()
