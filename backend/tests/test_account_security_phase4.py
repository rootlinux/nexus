import os
import secrets
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db
from app.api.routes.users import get_current_user
from app.core.security import get_password_hash
from app.main import app
from app.models.admin_password_reset_token import AdminPasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.invite import InviteCode, InviteType
from app.models.invite_usage import InviteUsage
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.services.account_security import hash_account_secret
from app.services.admin_security import hash_admin_password_reset_secret


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        if self._value is None:
            raise AssertionError("Expected scalar value")
        return self._value

    def scalar(self):
        return self._value


class _ListResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class FakeAccountSecurityDB:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.verification_tokens: list[EmailVerificationToken] = []
        self.password_reset_tokens: list[PasswordResetToken] = []
        self.admin_password_reset_tokens: list[AdminPasswordResetToken] = []
        self.refresh_tokens: list[RefreshToken] = []
        self.invites: dict[str, InviteCode] = {}
        self.invite_usages: list[InviteUsage] = []
        self._next_user_id = 100
        self._next_verification_token_id = 1
        self._next_password_reset_token_id = 1
        self._next_admin_password_reset_token_id = 1
        self._next_refresh_token_id = 1
        self.commit_count = 0
        self.fail_commit = False

    async def execute(self, statement):
        params = statement.compile().params
        statement_text = str(statement)
        if not hasattr(statement, "column_descriptions"):
            table_name = getattr(getattr(statement, "table", None), "name", "")
            token_id = next((value for key, value in params.items() if key.startswith("id_")), None)
            used_at = params.get("used_at")
            if table_name == "email_verification_tokens":
                token = next((item for item in self.verification_tokens if item.id == token_id), None)
            elif table_name == "password_reset_tokens":
                token = next((item for item in self.password_reset_tokens if item.id == token_id), None)
            elif table_name == "admin_password_reset_tokens":
                token = next((item for item in self.admin_password_reset_tokens if item.id == token_id), None)
            else:
                raise AssertionError(f"Unexpected statement without entity metadata: {statement}")

            if token is None or token.used_at is not None or token.revoked_at is not None or token.expires_at < used_at:
                return _ScalarResult(None)

            token.used_at = used_at
            return _ScalarResult(token.id)

        entity = statement.column_descriptions[0].get("entity")

        if entity is User:
            user_id = next((value for key, value in params.items() if "id" in key), None)
            if user_id is not None:
                return _ScalarResult(self.users.get(int(user_id)))

            identifiers = [value for key, value in params.items() if "username" in key or "email" in key]
            if identifiers:
                for user in self.users.values():
                    if user.username in identifiers or user.email in identifiers:
                        return _ScalarResult(user)
            return _ScalarResult(None)

        if entity is InviteCode:
            code = next((value for key, value in params.items() if "code" in key), None)
            return _ScalarResult(self.invites.get(code))

        if entity is EmailVerificationToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            if token_hash is not None:
                token = next((item for item in self.verification_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            tokens = [item for item in self.verification_tokens if user_id is None or item.user_id == int(user_id)]
            if "used_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.revoked_at is None]
            return _ListResult(tokens)

        if entity is PasswordResetToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            if token_hash is not None:
                token = next((item for item in self.password_reset_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            tokens = [item for item in self.password_reset_tokens if user_id is None or item.user_id == int(user_id)]
            if "used_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.revoked_at is None]
            return _ListResult(tokens)

        if entity is AdminPasswordResetToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            if token_hash is not None:
                token = next((item for item in self.admin_password_reset_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            tokens = [item for item in self.admin_password_reset_tokens if user_id is None or item.user_id == int(user_id)]
            if "used_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.revoked_at is None]
            return _ListResult(tokens)

        if entity is RefreshToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            if token_hash is not None:
                token = next((item for item in self.refresh_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            tokens = [item for item in self.refresh_tokens if user_id is None or item.user_id == int(user_id)]
            if "refresh_tokens.revoked = false" in statement_text.lower():
                tokens = [item for item in tokens if not item.revoked]
            return _ListResult(tokens)

        if entity is WebAuthnCredential:
            return _ScalarResult(None)

        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        if isinstance(instance, User):
            if instance.id is None:
                instance.id = self._next_user_id
                self._next_user_id += 1
            if instance.created_at is None:
                instance.created_at = datetime.now(timezone.utc)
            self.users[instance.id] = instance
        elif isinstance(instance, EmailVerificationToken):
            if instance.id is None:
                instance.id = self._next_verification_token_id
                self._next_verification_token_id += 1
            self.verification_tokens.append(instance)
        elif isinstance(instance, PasswordResetToken):
            if instance.id is None:
                instance.id = self._next_password_reset_token_id
                self._next_password_reset_token_id += 1
            self.password_reset_tokens.append(instance)
        elif isinstance(instance, AdminPasswordResetToken):
            if instance.id is None:
                instance.id = self._next_admin_password_reset_token_id
                self._next_admin_password_reset_token_id += 1
            self.admin_password_reset_tokens.append(instance)
        elif isinstance(instance, RefreshToken):
            if instance.id is None:
                instance.id = self._next_refresh_token_id
                self._next_refresh_token_id += 1
            self.refresh_tokens.append(instance)
        elif isinstance(instance, InviteUsage):
            self.invite_usages.append(instance)

    async def flush(self):
        return None

    async def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            self.fail_commit = False
            raise RuntimeError("commit failed")
        return None

    async def rollback(self):
        return None

    async def refresh(self, instance):
        return None

def build_user(
    user_id: int,
    *,
    username: str,
    email: str,
    password: str,
    verified: bool = True,
    must_change_password: bool = False,
) -> User:
    return User(
        id=user_id,
        username=username,
        display_name=username.title(),
        email=email,
        password_hash=get_password_hash(password),
        created_at=datetime.now(timezone.utc),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
        must_change_password=must_change_password,
    )


def build_invite(code: str, creator: User) -> InviteCode:
    invite = InviteCode(
        id=1,
        code=code,
        invite_type=InviteType.GENERIC,
        created_by_id=creator.id,
        max_uses=1,
        current_uses=0,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    invite.created_by_user = creator
    return invite


class AccountSecurityPhase4Tests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.db = FakeAccountSecurityDB()

        async def override_db():
            yield self.db

        async def _noop_rate_limit(*args, **kwargs):
            return None

        app.dependency_overrides[get_db] = override_db
        self.rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", _noop_rate_limit)
        self.rate_limit_patch.start()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.rate_limit_patch.stop()

    def _client(self, *, raise_server_exceptions: bool = True) -> TestClient:
        return TestClient(app, base_url="http://localhost", raise_server_exceptions=raise_server_exceptions)

    def _set_current_user(self, user: User):
        async def override_current_user():
            return user

        app.dependency_overrides[get_current_user] = override_current_user

    def test_register_creates_unverified_user_and_hashed_verification_artifact(self):
        creator = build_user(1, username="inviter", email="inviter@example.com", password="Inviter!Pass1")
        self.db.users[creator.id] = creator
        self.db.invites["INVITE123"] = build_invite("INVITE123", creator)
        client = self._client()

        audit_mock = AsyncMock()
        with patch("app.api.routes.auth.write_audit_log", audit_mock), patch("app.api.routes.auth.send_verification_email", new=AsyncMock()) as mail_mock:
            response = client.post(
                "/api/auth/register",
                json={
                    "username": "newmember",
                    "display_name": "New Member",
                    "email": "newmember@example.com",
                    "password": "Str0ng!Pass1",
                    "invite_code": "INVITE123",
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "pending_email_verification")
        user = next(user for user in self.db.users.values() if user.username == "newmember")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(len(self.db.verification_tokens), 1)
        token = self.db.verification_tokens[0]
        self.assertEqual(token.user_id, user.id)
        self.assertNotEqual(token.token_hash, "newmember@example.com")
        self.assertEqual(len(self.db.refresh_tokens), 0)
        mail_mock.assert_awaited_once()
        self.assertIn("email_verification_token_issued", [call.kwargs["action"] for call in audit_mock.await_args_list])

    def test_verify_email_completion_is_one_time_and_marks_user_verified(self):
        user = build_user(2, username="verifyme", email="verifyme@example.com", password="Str0ng!Pass1", verified=False)
        self.db.users[user.id] = user
        raw_secret = "verify-secret-token-value-0123456789"
        self.db.verification_tokens.append(
            EmailVerificationToken(
                id=1,
                user_id=user.id,
                email=user.email,
                token_hash=hash_account_secret(raw_secret),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            first = client.post("/api/auth/verify-email/complete", json={"token": raw_secret})
            second = client.post("/api/auth/verify-email/complete", json={"token": raw_secret})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "verified")
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json(), {"detail": "Invalid or expired verification link"})

    def test_expired_verification_token_fails(self):
        user = build_user(3, username="late", email="late@example.com", password="Str0ng!Pass1", verified=False)
        self.db.users[user.id] = user
        raw_secret = "expired-verification-token-value"
        self.db.verification_tokens.append(
            EmailVerificationToken(
                id=2,
                user_id=user.id,
                email=user.email,
                token_hash=hash_account_secret(raw_secret),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            response = client.post("/api/auth/verify-email/complete", json={"token": raw_secret})

        self.assertEqual(response.status_code, 400)

    def test_password_reset_request_is_neutral_and_stores_hashed_artifact(self):
        user = build_user(4, username="resetme", email="resetme@example.com", password="Old!Password1")
        self.db.users[user.id] = user
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()) as audit_mock, patch("app.api.routes.auth.send_password_reset_email", new=AsyncMock()) as mail_mock:
            existing = client.post("/api/auth/password-reset/request", json={"email": user.email})
            missing = client.post("/api/auth/password-reset/request", json={"email": "unknown@example.com"})

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(existing.json(), missing.json())
        self.assertEqual(len(self.db.password_reset_tokens), 1)
        self.assertNotEqual(self.db.password_reset_tokens[0].token_hash, "reset-secret")
        mail_mock.assert_awaited_once()
        actions = [call.kwargs["action"] for call in audit_mock.await_args_list]
        self.assertIn("password_reset_requested", actions)
        self.assertIn("password_reset_token_issued", actions)

    def test_password_reset_completion_revokes_sessions_and_allows_new_password(self):
        user = build_user(5, username="recover", email="recover@example.com", password="Old!Password1")
        self.db.users[user.id] = user
        raw_secret = "usable-reset-token-value-0123456789"
        self.db.password_reset_tokens.append(
            PasswordResetToken(
                id=1,
                user_id=user.id,
                email=user.email,
                token_hash=hash_account_secret(raw_secret),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        self.db.admin_password_reset_tokens.append(
            AdminPasswordResetToken(
                id=7,
                user_id=user.id,
                token_hash=hash_admin_password_reset_secret("admin-reset-secret-value-0123456789"),
                issued_by_user_id=99,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        self.db.refresh_tokens.extend(
            [
                RefreshToken(id=1, user_id=user.id, token_hash="hash-a", expires_at=datetime.now(timezone.utc) + timedelta(days=7), revoked=False),
                RefreshToken(id=2, user_id=user.id, token_hash="hash-b", expires_at=datetime.now(timezone.utc) + timedelta(days=7), revoked=False),
            ]
        )
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            reset_response = client.post(
                "/api/auth/password-reset/complete",
                json={"token": raw_secret, "new_password": "New!Password2"},
            )

        self.assertEqual(reset_response.status_code, 204)
        self.assertTrue(all(token.revoked for token in self.db.refresh_tokens))
        self.assertIsNotNone(self.db.admin_password_reset_tokens[0].revoked_at)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            old_login = client.post("/api/auth/login", json={"username": user.username, "password": "Old!Password1"})
            new_login = client.post("/api/auth/login", json={"username": user.username, "password": "New!Password2"})

        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)
        self.assertIn("access_token", new_login.json())

    def test_unverified_login_is_denied_and_protected_route_stays_gated(self):
        user = build_user(6, username="pending", email="pending@example.com", password="Str0ng!Pass1", verified=False)
        self.db.users[user.id] = user
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            login_response = client.post("/api/auth/login", json={"username": user.username, "password": "Str0ng!Pass1"})
        self.assertEqual(login_response.status_code, 403)
        self.assertEqual(login_response.json()["detail"]["code"], "EMAIL_VERIFICATION_REQUIRED")

        with patch("app.api.deps._decode_access_token", return_value=SimpleNamespace(user_id=user.id, username=user.username, admin_role=None)):
            me_response = client.get("/api/auth/me", headers={"Authorization": "Bearer crafted-token"})
        self.assertEqual(me_response.status_code, 403)
        self.assertEqual(me_response.json()["detail"]["code"], "EMAIL_VERIFICATION_REQUIRED")

    def test_password_change_revokes_public_admin_reset_tokens_and_sessions(self):
        user = build_user(7, username="selfserve", email="selfserve@example.com", password="Old!Password1")
        self.db.users[user.id] = user
        self.db.password_reset_tokens.extend(
            [
                PasswordResetToken(
                    id=10,
                    user_id=user.id,
                    email=user.email,
                    token_hash="public-token-a",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                ),
                PasswordResetToken(
                    id=11,
                    user_id=user.id,
                    email=user.email,
                    token_hash="public-token-b",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                ),
            ]
        )
        self.db.admin_password_reset_tokens.append(
            AdminPasswordResetToken(
                id=12,
                user_id=user.id,
                token_hash="admin-token-a",
                issued_by_user_id=101,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        self.db.refresh_tokens.append(
            RefreshToken(id=13, user_id=user.id, token_hash="refresh-a", expires_at=datetime.now(timezone.utc) + timedelta(days=7), revoked=False)
        )
        self._set_current_user(user)
        client = self._client()

        with patch("app.api.routes.users.write_audit_log", new=AsyncMock()) as audit_mock:
            response = client.post(
                "/api/users/me/password",
                json={"current_password": "Old!Password1", "new_password": "New!Password2"},
                headers={"Authorization": "Bearer crafted-token"},
            )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(all(token.revoked_at is not None for token in self.db.password_reset_tokens))
        self.assertTrue(all(token.revoked_at is not None for token in self.db.admin_password_reset_tokens))
        self.assertTrue(all(token.revoked for token in self.db.refresh_tokens))
        self.assertEqual(audit_mock.await_args.kwargs["after"]["revoked_public_reset_tokens"], 2)
        self.assertEqual(audit_mock.await_args.kwargs["after"]["revoked_admin_reset_tokens"], 1)

    def test_admin_reset_fallback_revokes_public_and_admin_reset_tokens(self):
        user = build_user(8, username="forced", email="forced@example.com", password="Old!Password1", must_change_password=True)
        self.db.users[user.id] = user
        public_secret = "public-secret-value-0123456789-public"
        admin_secret = "admin-secret-value-0123456789-admin"
        self.db.password_reset_tokens.append(
            PasswordResetToken(
                id=20,
                user_id=user.id,
                email=user.email,
                token_hash=hash_account_secret(public_secret),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        used_token = AdminPasswordResetToken(
            id=21,
            user_id=user.id,
            token_hash=hash_admin_password_reset_secret(admin_secret),
            issued_by_user_id=55,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        stale_admin_token = AdminPasswordResetToken(
            id=22,
            user_id=user.id,
            token_hash="another-admin-token-hash",
            issued_by_user_id=56,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        self.db.admin_password_reset_tokens.extend([used_token, stale_admin_token])
        self.db.refresh_tokens.append(
            RefreshToken(id=23, user_id=user.id, token_hash="refresh-b", expires_at=datetime.now(timezone.utc) + timedelta(days=7), revoked=False)
        )
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()) as audit_mock:
            response = client.post(
                "/api/auth/password-reset/complete",
                json={"token": admin_secret, "new_password": "New!Password2"},
            )

        self.assertEqual(response.status_code, 204)
        self.assertIsNotNone(used_token.used_at)
        self.assertIsNotNone(self.db.password_reset_tokens[0].revoked_at)
        self.assertIsNotNone(stale_admin_token.revoked_at)
        self.assertTrue(self.db.refresh_tokens[0].revoked)
        self.assertEqual(audit_mock.await_args.kwargs["after"]["invalidated_public_reset_tokens"], 1)
        self.assertEqual(audit_mock.await_args.kwargs["after"]["invalidated_admin_reset_tokens"], 1)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            public_retry = client.post(
                "/api/auth/password-reset/complete",
                json={"token": public_secret, "new_password": "Another!Password3"},
            )
            admin_retry = client.post(
                "/api/auth/password-reset/complete",
                json={"token": admin_secret, "new_password": "Another!Password3"},
            )

        self.assertEqual(public_retry.status_code, 400)
        self.assertEqual(admin_retry.status_code, 400)

    def test_register_canonicalizes_email_and_login_resend_reset_accept_case_variants(self):
        creator = build_user(9, username="inviter2", email="inviter2@example.com", password="Inviter!Pass1")
        self.db.users[creator.id] = creator
        self.db.invites["INVITE456"] = build_invite("INVITE456", creator)
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(),
        ):
            register_response = client.post(
                "/api/auth/register",
                json={
                    "username": "mixedcase",
                    "display_name": "Mixed Case",
                    "email": "User@Example.COM",
                    "password": "Str0ng!Pass1",
                    "invite_code": "INVITE456",
                },
            )

        self.assertEqual(register_response.status_code, 201)
        registered_user = next(user for user in self.db.users.values() if user.username == "mixedcase")
        self.assertEqual(registered_user.email, "user@example.com")
        registered_user.email_verified_at = datetime.now(timezone.utc)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            login_response = client.post(
                "/api/auth/login",
                json={"username": "USER@example.com", "password": "Str0ng!Pass1"},
            )
        self.assertEqual(login_response.status_code, 200)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(),
        ):
            resend_response = client.post("/api/auth/verify-email/request", json={"email": " USER@example.com "})
        self.assertEqual(resend_response.status_code, 200)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_password_reset_email",
            new=AsyncMock(),
        ):
            reset_response = client.post("/api/auth/password-reset/request", json={"email": " USER@example.com "})
        self.assertEqual(reset_response.status_code, 200)

        self.db.invites["INVITE789"] = build_invite("INVITE789", creator)
        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(),
        ):
            duplicate_response = client.post(
                "/api/auth/register",
                json={
                    "username": "mixedcase2",
                    "display_name": "Mixed Case Two",
                    "email": "user@example.com",
                    "password": "Str0ng!Pass1",
                    "invite_code": "INVITE789",
                },
            )
        self.assertEqual(duplicate_response.status_code, 400)

    def test_registration_send_failure_happens_after_commit_and_keeps_token(self):
        creator = build_user(10, username="inviter3", email="inviter3@example.com", password="Inviter!Pass1")
        self.db.users[creator.id] = creator
        self.db.invites["INVITE999"] = build_invite("INVITE999", creator)
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            response = client.post(
                "/api/auth/register",
                json={
                    "username": "mailfail",
                    "display_name": "Mail Fail",
                    "email": "mailfail@example.com",
                    "password": "Str0ng!Pass1",
                    "invite_code": "INVITE999",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.db.verification_tokens), 1)
        self.assertGreaterEqual(self.db.commit_count, 2)

    def test_registration_capture_mode_survives_unwritable_relative_mail_dir(self):
        creator = build_user(13, username="inviter5", email="inviter5@example.com", password="Inviter!Pass1")
        self.db.users[creator.id] = creator
        self.db.invites["INVITEFALLBACK"] = build_invite("INVITEFALLBACK", creator)
        client = self._client()
        original_tmpdir = os.environ.get("TMPDIR")
        original_cwd = os.getcwd()
        from app.core.config import settings
        original_provider = settings.MAIL_PROVIDER
        original_capture_dir = settings.MAIL_CAPTURE_DIR

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()):
            with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as tmp_dir:
                os.chdir(workspace_dir)
                os.chmod(workspace_dir, stat.S_IREAD | stat.S_IEXEC)
                os.environ["TMPDIR"] = tmp_dir
                settings.MAIL_PROVIDER = "capture"
                settings.MAIL_CAPTURE_DIR = "tmp/mail"
                try:
                    response = client.post(
                        "/api/auth/register",
                        json={
                            "username": "capturefallback",
                            "display_name": "Capture Fallback",
                            "email": "capturefallback@example.com",
                            "password": "Str0ng!Pass1",
                            "invite_code": "INVITEFALLBACK",
                        },
                    )
                finally:
                    os.chdir(original_cwd)
                    os.chmod(workspace_dir, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
                    settings.MAIL_PROVIDER = original_provider
                    settings.MAIL_CAPTURE_DIR = original_capture_dir
                    if original_tmpdir is None:
                        os.environ.pop("TMPDIR", None)
                    else:
                        os.environ["TMPDIR"] = original_tmpdir

        self.assertEqual(response.status_code, 201)

    def test_registration_commit_failure_prevents_email_send(self):
        creator = build_user(11, username="inviter4", email="inviter4@example.com", password="Inviter!Pass1")
        self.db.users[creator.id] = creator
        self.db.invites["INVITEABC"] = build_invite("INVITEABC", creator)
        self.db.fail_commit = True
        client = self._client(raise_server_exceptions=False)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(),
        ) as mail_mock:
            response = client.post(
                "/api/auth/register",
                json={
                    "username": "commitfail",
                    "display_name": "Commit Fail",
                    "email": "commitfail@example.com",
                    "password": "Str0ng!Pass1",
                    "invite_code": "INVITEABC",
                },
            )

        self.assertEqual(response.status_code, 500)
        mail_mock.assert_not_awaited()

    def test_resend_and_reset_requests_commit_before_send_and_stay_neutral_on_mail_failure(self):
        user = build_user(12, username="neutral", email="neutral@example.com", password="Old!Password1", verified=False)
        self.db.users[user.id] = user
        client = self._client()

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_verification_email",
            new=AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            resend_response = client.post("/api/auth/verify-email/request", json={"email": "NEUTRAL@example.com"})

        self.assertEqual(resend_response.status_code, 200)
        self.assertEqual(len(self.db.verification_tokens), 1)

        with patch("app.api.routes.auth.write_audit_log", new=AsyncMock()), patch(
            "app.api.routes.auth.send_password_reset_email",
            new=AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            reset_response = client.post("/api/auth/password-reset/request", json={"email": "NEUTRAL@example.com"})

        self.assertEqual(reset_response.status_code, 200)
        self.assertEqual(len(self.db.password_reset_tokens), 1)


if __name__ == "__main__":
    unittest.main()
