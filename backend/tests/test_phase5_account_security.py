import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db
from app.api.routes.auth import get_current_user
from app.core.datetime_utils import ensure_utc_datetime
from app.core.security import get_password_hash, verify_password
from app.main import app
from app.models.admin_password_reset_token import AdminPasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.email_change_token import EmailChangeToken
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.services.account_security import hash_account_secret


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


class FakePhase5DB:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.refresh_tokens: list[RefreshToken] = []
        self.email_change_tokens: list[EmailChangeToken] = []
        self.verification_tokens: list[EmailVerificationToken] = []
        self._next_email_change_token_id = 1
        self._next_verification_token_id = 1

    async def execute(self, statement):
        if not hasattr(statement, "column_descriptions"):
            table_name = getattr(getattr(statement, "table", None), "name", "")
            token_id = next((value for key, value in statement.compile().params.items() if key.startswith("id")), None)
            used_at = statement.compile().params.get("used_at")
            if table_name == "email_change_tokens":
                token = next((item for item in self.email_change_tokens if item.id == int(token_id)), None)
            elif table_name == "email_verification_tokens":
                token = next((item for item in self.verification_tokens if item.id == int(token_id)), None)
            else:
                raise AssertionError(f"Unexpected statement without entity metadata: {statement}")

            if token is None:
                return _ScalarResult(None)

            expires_at = ensure_utc_datetime(token.expires_at)
            consumed_at = ensure_utc_datetime(used_at)
            if token.used_at is not None or token.revoked_at is not None or expires_at < consumed_at:
                return _ScalarResult(None)

            token.used_at = consumed_at
            return _ScalarResult(token.id)

        entity = statement.column_descriptions[0].get("entity")
        params = statement.compile().params
        statement_text = str(statement)

        if entity is User:
            user_id = next((value for key, value in params.items() if key.startswith("id")), None)
            if user_id is not None and "users.id !=" not in statement_text:
                return _ScalarResult(self.users.get(int(user_id)))

            email = next((value for key, value in params.items() if "email" in key), None)
            exclude_id = next((value for key, value in params.items() if key.startswith("id_")), None)
            if email is not None:
                for user in self.users.values():
                    if user.email == email and (exclude_id is None or user.id != int(exclude_id)):
                        return _ScalarResult(user)
                return _ScalarResult(None)

            return _ScalarResult(None)

        if entity is RefreshToken:
            token_id = next((value for key, value in params.items() if key == "id_1"), None)
            user_id = next((value for key, value in params.items() if "user_id" in key), None)
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)

            if token_hash is not None:
                token = next((item for item in self.refresh_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            if token_id is not None and "refresh_tokens.user_id" in statement_text:
                token = next(
                    (
                        item
                        for item in self.refresh_tokens
                        if item.id == int(token_id) and item.user_id == int(user_id)
                    ),
                    None,
                )
                return _ScalarResult(token)

            tokens = list(self.refresh_tokens)
            if user_id is not None:
                tokens = [item for item in tokens if item.user_id == int(user_id)]
            if "refresh_tokens.revoked = false" in statement_text.lower():
                tokens = [item for item in tokens if not item.revoked]
            if token_id is not None and "refresh_tokens.id =" in statement_text.lower():
                token = next((item for item in tokens if item.id == int(token_id)), None)
                return _ScalarResult(token)
            return _ListResult(tokens)

        if entity in {PasswordResetToken, AdminPasswordResetToken}:
            return _ListResult([])

        if entity is EmailChangeToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            user_id = next((value for key, value in params.items() if "user_id" in key), None)

            if token_hash is not None:
                token = next((item for item in self.email_change_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            tokens = list(self.email_change_tokens)
            if user_id is not None:
                tokens = [item for item in tokens if item.user_id == int(user_id)]
            if "used_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.revoked_at is None]
            return _ListResult(tokens)

        if entity is EmailVerificationToken:
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            user_id = next((value for key, value in params.items() if "user_id" in key), None)

            if token_hash is not None:
                token = next((item for item in self.verification_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)

            tokens = list(self.verification_tokens)
            if user_id is not None:
                tokens = [item for item in tokens if item.user_id == int(user_id)]
            if "used_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.used_at is None]
            if "revoked_at IS NULL" in statement_text:
                tokens = [item for item in tokens if item.revoked_at is None]
            return _ListResult(tokens)

        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        if isinstance(instance, User):
            self.users[instance.id] = instance
        elif isinstance(instance, RefreshToken):
            self.refresh_tokens.append(instance)
        elif isinstance(instance, EmailChangeToken):
            if instance.id is None:
                instance.id = self._next_email_change_token_id
                self._next_email_change_token_id += 1
            self.email_change_tokens.append(instance)
        elif isinstance(instance, EmailVerificationToken):
            if instance.id is None:
                instance.id = self._next_verification_token_id
                self._next_verification_token_id += 1
            self.verification_tokens.append(instance)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, instance):
        return None


def build_user(user_id: int, *, username: str, email: str, password: str, verified: bool = True) -> User:
    return User(
        id=user_id,
        username=username,
        display_name=username.title(),
        email=email,
        password_hash=get_password_hash(password),
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow() if verified else None,
        must_change_password=False,
    )


def build_refresh_token(
    token_id: int,
    *,
    user_id: int,
    created_offset_minutes: int,
    revoked: bool = False,
    device_label: str = "Chrome on macOS",
) -> RefreshToken:
    created_at = datetime.utcnow() - timedelta(minutes=created_offset_minutes)
    return RefreshToken(
        id=token_id,
        user_id=user_id,
        token_hash=f"token-hash-{token_id}",
        expires_at=datetime.utcnow() + timedelta(days=7),
        revoked=revoked,
        created_at=created_at,
        last_used_at=created_at + timedelta(minutes=1),
        device_label=device_label,
        device_fingerprint=f"fingerprint-{token_id}",
    )


class Phase5AccountSecurityTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.db = FakePhase5DB()

        async def override_db():
            yield self.db

        async def override_current_user():
            return self.current_user

        async def _noop_rate_limit(*args, **kwargs):
            return None

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", _noop_rate_limit)
        self.rate_limit_patch.start()
        self.audit_patch = patch("app.api.routes.auth.write_audit_log", new=AsyncMock())
        self.audit_mock = self.audit_patch.start()
        self.user_audit_patch = patch("app.api.routes.users.write_audit_log", new=AsyncMock())
        self.user_audit_mock = self.user_audit_patch.start()

        self.current_user = build_user(1, username="owner", email="owner@example.com", password="Curr3nt!Pass1")
        setattr(self.current_user, "_current_session_id", 101)
        self.other_user = build_user(2, username="other", email="other@example.com", password="Curr3nt!Pass1")
        self.db.add(self.current_user)
        self.db.add(self.other_user)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.rate_limit_patch.stop()
        self.audit_patch.stop()
        self.user_audit_patch.stop()

    def _client(self):
        return TestClient(app, base_url="http://localhost", raise_server_exceptions=True)

    def test_list_sessions_only_returns_active_sessions_for_current_user(self):
        self.db.add(build_refresh_token(101, user_id=self.current_user.id, created_offset_minutes=5))
        self.db.add(build_refresh_token(102, user_id=self.current_user.id, created_offset_minutes=25, device_label="Safari on iPhone"))
        self.db.add(build_refresh_token(103, user_id=self.current_user.id, created_offset_minutes=45, revoked=True))
        self.db.add(build_refresh_token(201, user_id=self.other_user.id, created_offset_minutes=15))

        with self._client() as client:
            response = client.get("/api/auth/sessions")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["sessions"]], [101, 102])
        self.assertTrue(payload["sessions"][0]["is_current"])
        self.assertEqual(payload["sessions"][1]["device_label"], "Safari on iPhone")

    def test_single_session_revoke_blocks_current_session_and_foreign_session(self):
        self.db.add(build_refresh_token(101, user_id=self.current_user.id, created_offset_minutes=5))
        self.db.add(build_refresh_token(201, user_id=self.other_user.id, created_offset_minutes=15))

        with self._client() as client:
            current_response = client.post("/api/auth/sessions/101/revoke")
            foreign_response = client.post("/api/auth/sessions/201/revoke")

        self.assertEqual(current_response.status_code, 400)
        self.assertIn("cannot be revoked", current_response.text)
        self.assertEqual(foreign_response.status_code, 404)
        audit_actions = [call.kwargs["action"] for call in self.audit_mock.await_args_list]
        self.assertIn("session_revoke_denied", audit_actions)

    def test_revoke_other_sessions_requires_current_password_and_preserves_current_session(self):
        self.db.add(build_refresh_token(101, user_id=self.current_user.id, created_offset_minutes=5))
        target_session = build_refresh_token(102, user_id=self.current_user.id, created_offset_minutes=35)
        self.db.add(target_session)

        with self._client() as client:
            denied = client.post("/api/auth/sessions/revoke-others", json={"current_password": "wrong-password"})
            allowed = client.post("/api/auth/sessions/revoke-others", json={"current_password": "Curr3nt!Pass1"})

        self.assertEqual(denied.status_code, 400)
        self.assertFalse(self.db.refresh_tokens[0].revoked)
        self.assertTrue(target_session.revoked)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["revoked_session_count"], 1)

    def test_email_change_request_requires_password_and_stores_hashed_token(self):
        send_email_mock = AsyncMock()
        with patch("app.api.routes.auth.send_email_change_email", send_email_mock):
            with self._client() as client:
                denied = client.post(
                    "/api/auth/email-change/request",
                    json={"new_email": "NewEmail@Example.com", "current_password": "wrong-password"},
                )
                allowed = client.post(
                    "/api/auth/email-change/request",
                    json={"new_email": "NewEmail@Example.com", "current_password": "Curr3nt!Pass1"},
                )

        self.assertEqual(denied.status_code, 400)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(len(self.db.email_change_tokens), 1)
        token_row = self.db.email_change_tokens[0]
        raw_secret = send_email_mock.await_args.kwargs["secret"]
        self.assertEqual(token_row.pending_email, "newemail@example.com")
        self.assertNotEqual(token_row.token_hash, raw_secret)
        self.assertEqual(token_row.token_hash, hash_account_secret(raw_secret))
        for call in self.audit_mock.await_args_list:
            serialized = repr(call.kwargs)
            self.assertNotIn(raw_secret, serialized)

    def test_email_change_request_is_neutral_when_canonical_email_is_already_used(self):
        with self._client() as client:
            response = client.post(
                "/api/auth/email-change/request",
                json={"new_email": "OTHER@EXAMPLE.COM", "current_password": "Curr3nt!Pass1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "If the new email is eligible, a confirmation link will be sent shortly.")
        self.assertEqual(self.db.email_change_tokens, [])

    def test_email_change_completion_updates_email_revokes_pending_tokens_and_sessions(self):
        self.db.add(build_refresh_token(101, user_id=self.current_user.id, created_offset_minutes=5))
        self.db.add(build_refresh_token(102, user_id=self.current_user.id, created_offset_minutes=25))
        stale_token = EmailChangeToken(
            id=1,
            user_id=self.current_user.id,
            pending_email="stale@example.com",
            token_hash=hash_account_secret("stale-secret"),
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            created_at=datetime.utcnow() - timedelta(minutes=5),
            used_at=None,
            revoked_at=None,
        )
        active_secret = "fresh-secret-token-material-0123456789"
        active_token = EmailChangeToken(
            id=2,
            user_id=self.current_user.id,
            pending_email="fresh@example.com",
            token_hash=hash_account_secret(active_secret),
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            created_at=datetime.utcnow(),
            used_at=None,
            revoked_at=None,
        )
        self.db.add(stale_token)
        self.db.add(active_token)

        with self._client() as client:
            response = client.post("/api/auth/email-change/complete", json={"token": active_secret})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verified")
        self.assertEqual(self.current_user.email, "fresh@example.com")
        self.assertIsNotNone(self.current_user.email_verified_at)
        self.assertIsNone(self.current_user.email_verified_at.tzinfo)
        self.assertIsNotNone(active_token.used_at)
        self.assertIsNotNone(stale_token.revoked_at)
        self.assertTrue(all(token.revoked for token in self.db.refresh_tokens))

    def test_email_verification_completion_normalizes_verified_timestamp_for_user_column(self):
        verification_secret = "verify-secret-token-material-0123456789"
        verification_token = EmailVerificationToken(
            id=1,
            user_id=self.current_user.id,
            email=self.current_user.email,
            token_hash=hash_account_secret(verification_secret),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            created_at=datetime.now(timezone.utc),
            used_at=None,
            revoked_at=None,
        )
        self.current_user.email_verified_at = None
        self.db.add(verification_token)

        with self._client() as client:
            response = client.post("/api/auth/verify-email/complete", json={"token": verification_secret})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verified")
        self.assertIsNotNone(self.current_user.email_verified_at)
        self.assertIsNone(self.current_user.email_verified_at.tzinfo)
        self.assertIsNotNone(verification_token.used_at)

    def test_password_change_enforces_step_up_and_revokes_sessions(self):
        self.db.add(build_refresh_token(101, user_id=self.current_user.id, created_offset_minutes=5))
        self.db.add(build_refresh_token(102, user_id=self.current_user.id, created_offset_minutes=15))

        with self._client() as client:
            denied = client.post(
                "/api/users/me/password",
                json={"current_password": "wrong-password", "new_password": "Newer!Pass2"},
            )
            allowed = client.post(
                "/api/users/me/password",
                json={"current_password": "Curr3nt!Pass1", "new_password": "Newer!Pass2"},
            )

        self.assertEqual(denied.status_code, 400)
        self.assertEqual(allowed.status_code, 204)
        self.assertTrue(verify_password("Newer!Pass2", self.current_user.password_hash))
        self.assertTrue(all(token.revoked for token in self.db.refresh_tokens))
        actions = [call.kwargs["action"] for call in self.user_audit_mock.await_args_list]
        self.assertIn("password.change_denied", actions)
        self.assertIn("password.change", actions)


if __name__ == "__main__":
    unittest.main()
