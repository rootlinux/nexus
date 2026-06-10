import base64
import asyncio
import os
import secrets
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.routes.webauthn import (
    delete_webauthn_credential,
    webauthn_auth_begin,
    webauthn_auth_complete,
    webauthn_recovery_register_begin,
    webauthn_recovery_register_complete,
    webauthn_register_begin,
    webauthn_register_complete,
)
from app.api.routes.admin import (
    delete_user_webauthn_credential,
    list_user_webauthn_credentials,
    SensitiveAdminActionRequest,
)
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.schemas.webauthn import (
    WebAuthnAuthBeginRequest,
    WebAuthnAuthCompleteRequest,
    WebAuthnCredentialDeleteRequest,
    WebAuthnRecoveryRegisterBeginRequest,
    WebAuthnRecoveryRegisterCompleteRequest,
    WebAuthnRegisterBeginRequest,
    WebAuthnRegisterCompleteRequest,
)


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ListScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _ListScalarResult(self._values)


class FakeWebAuthnDB:
    def __init__(self, user: User, credential: WebAuthnCredential):
        self.user = user
        self.credential = credential
        self.added = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is WebAuthnCredential:
            return _ScalarResult(self.credential)
        if entity is User:
            return _ScalarResult(self.user)
        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        for index, instance in enumerate(self.added, start=1):
            if getattr(instance, "id", None) is None:
                instance.id = index

    async def commit(self):
        return None

    async def refresh(self, instance):
        return None

    async def rollback(self):
        return None


class FakeWebAuthnBeginDB:
    def __init__(self, credentials: list[WebAuthnCredential]):
        self.credentials = credentials

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is WebAuthnCredential:
            return _ListResult(self.credentials)
        raise AssertionError(f"Unexpected entity {entity}")


class FakeWebAuthnRegisterDB:
    def __init__(self, existing_credential: WebAuthnCredential | None = None, *, fail_commit: bool = False):
        self.existing_credential = existing_credential
        self.fail_commit = fail_commit
        self.added: list[object] = []
        self.refreshed: list[object] = []
        self.rollback_called = False

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is WebAuthnCredential:
            return _ScalarResult(self.existing_credential)
        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return None

    async def refresh(self, instance):
        self.refreshed.append(instance)

    async def rollback(self):
        self.rollback_called = True


class FakeWebAuthnRecoveryDB:
    def __init__(self, *, user: User, existing_credential: WebAuthnCredential | None = None):
        self.user = user
        self.existing_credential = existing_credential
        self.added: list[object] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is User:
            return _ScalarResult(self.user)
        if entity is WebAuthnCredential:
            return _ScalarResult(self.existing_credential)
        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        for index, instance in enumerate(self.added, start=1):
            if getattr(instance, "id", None) is None:
                instance.id = index

    async def commit(self):
        return None

    async def refresh(self, instance):
        return None

    async def rollback(self):
        return None


class FakeWebAuthnDeleteDB:
    def __init__(
        self,
        *,
        owned_credential: WebAuthnCredential | None,
        user_credentials: list[WebAuthnCredential],
        refresh_tokens: list[RefreshToken] | None = None,
    ):
        self.owned_credential = owned_credential
        self.user_credentials = list(user_credentials)
        self.refresh_tokens = list(refresh_tokens or [])
        self.deleted: list[object] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        params = statement.compile().params
        if entity is WebAuthnCredential:
            if "id_1" in params and "user_id_1" in params:
                return _ScalarResult(self.owned_credential)
            if "user_id_1" in params:
                user_id = params["user_id_1"]
                return _ListResult([cred for cred in self.user_credentials if cred.user_id == user_id])
        if entity is RefreshToken:
            user_id = params.get("user_id_1")
            active = [token for token in self.refresh_tokens if token.user_id == user_id and not token.revoked]
            return _ListResult(active)
        raise AssertionError(f"Unexpected execute statement for entity {entity}")

    async def delete(self, instance):
        self.deleted.append(instance)
        self.user_credentials = [cred for cred in self.user_credentials if cred is not instance]

    async def commit(self):
        return None


class FakeAdminWebAuthnDB:
    def __init__(
        self,
        *,
        target_user: User | None,
        credential: WebAuthnCredential | None = None,
        credentials: list[WebAuthnCredential] | None = None,
        refresh_tokens: list[RefreshToken] | None = None,
    ):
        self.target_user = target_user
        self.credential = credential
        self.credentials = list(credentials or [])
        self.refresh_tokens = list(refresh_tokens or [])
        self.deleted: list[object] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        params = statement.compile().params
        statement_text = str(statement)

        if entity is User:
            return _ScalarResult(self.target_user)

        if entity is WebAuthnCredential:
            if "id_1" in params and "user_id_1" in params:
                return _ScalarResult(self.credential)
            return _ListResult(self.credentials)

        if entity is RefreshToken:
            user_id = params.get("user_id_1")
            active = [token for token in self.refresh_tokens if token.user_id == user_id and not token.revoked]
            if "refresh_tokens.revoked = false" in statement_text.lower():
                return _ListResult(active)
            return _ListResult([token for token in self.refresh_tokens if token.user_id == user_id])

        raise AssertionError(f"Unexpected execute statement for entity {entity}")

    async def delete(self, instance):
        self.deleted.append(instance)
        self.credentials = [credential for credential in self.credentials if credential is not instance]

    async def commit(self):
        return None


def build_request() -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/webauthn/auth/complete",
        "headers": [
            (b"user-agent", b"pytest"),
            (b"accept-language", b"en-US"),
            (b"accept-encoding", b"gzip"),
            (b"sec-ch-ua-platform", b"macOS"),
        ],
    }


def build_delete_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/api/webauthn/credentials/1",
            "headers": [],
        }
    )


def build_admin_request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
        }
    )


def build_user(user_id: int) -> User:
    return User(
        id=user_id,
        username=f"user{user_id}",
        email=f"user{user_id}@example.com",
        password_hash="hash",
        created_at=datetime.utcnow(),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
    )


class WebAuthnAuthSourceOfTruthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rate_limit_patch = patch("app.api.routes.webauthn.enforce_rate_limits", new=AsyncMock())
        self.rate_limit_patch.start()

    async def asyncTearDown(self):
        self.rate_limit_patch.stop()

    async def test_register_begin_requires_current_password(self):
        user = build_user(5)
        user.password_hash = "hashed-password"

        with self.assertRaises(HTTPException) as exc_info:
            await webauthn_register_begin(
                Request(build_request()),
                WebAuthnRegisterBeginRequest(name="Laptop key", current_password=None),
                current_user=user,
            )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Current password required to add a security key")

    async def test_register_begin_rejects_wrong_password(self):
        user = build_user(5)
        user.password_hash = "hashed-password"

        with patch("app.api.routes.webauthn.verify_password", return_value=False):
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_register_begin(
                    Request(build_request()),
                    WebAuthnRegisterBeginRequest(name="Laptop key", current_password="wrong"),
                    current_user=user,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Current password is incorrect")

    async def test_register_begin_accepts_correct_password_and_returns_options(self):
        user = build_user(5)
        user.password_hash = "hashed-password"
        options = SimpleNamespace(challenge=b"challenge-bytes")

        with patch("app.api.routes.webauthn.verify_password", return_value=True) as verify_password_mock, patch(
            "app.api.routes.webauthn.generate_registration_options",
            return_value=options,
        ), patch(
            "app.api.routes.webauthn.options_to_json",
            return_value='{"challenge":"abc","rp":{"name":"Test"}}',
        ), patch(
            "app.api.routes.webauthn._set_redis_challenge",
            new=AsyncMock(),
        ) as set_redis_mock:
            response = await webauthn_register_begin(
                Request(build_request()),
                WebAuthnRegisterBeginRequest(name="Laptop key", current_password="correct"),
                current_user=user,
            )

        verify_password_mock.assert_called_once_with("correct", user.password_hash)
        set_redis_mock.assert_awaited_once_with("webauthn:reg_challenge:", str(user.id), options.challenge)
        self.assertEqual(response.options, {"challenge": "abc", "rp": {"name": "Test"}})

    async def test_recovery_register_begin_accepts_recovery_token_for_configured_admin_without_key(self):
        user = build_user(51)
        user.staff_permission = StaffPermission(id=15, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        db = FakeWebAuthnRecoveryDB(user=user, existing_credential=None)
        options = SimpleNamespace(challenge=b"recovery-challenge")

        with patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ENABLE_ADMIN_WEBAUTHN_RECOVERY",
            True,
        ), patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
            user.email,
        ), patch(
            "app.api.routes.webauthn.decode_admin_webauthn_recovery_token",
            return_value={"user_id": user.id, "jti": "recovery-jti"},
        ), patch(
            "app.api.routes.webauthn.get_admin_webauthn_recovery_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.generate_registration_options",
            return_value=options,
        ), patch(
            "app.api.routes.webauthn.options_to_json",
            return_value='{"challenge":"abc","rp":{"name":"Test"}}',
        ), patch(
            "app.api.routes.webauthn._set_redis_challenge",
            new=AsyncMock(),
        ) as set_redis_mock:
            response = await webauthn_recovery_register_begin(
                Request(build_request()),
                WebAuthnRecoveryRegisterBeginRequest(recovery_token="recovery-token"),
                db=db,
            )

        set_redis_mock.assert_awaited_once_with("webauthn:reg_challenge:", str(user.id), options.challenge)
        self.assertEqual(response.options, {"challenge": "abc", "rp": {"name": "Test"}})

    async def test_recovery_register_begin_allows_valid_token_even_if_identifier_changes_after_issuance(self):
        user = build_user(511)
        user.staff_permission = StaffPermission(id=151, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        db = FakeWebAuthnRecoveryDB(user=user, existing_credential=None)
        options = SimpleNamespace(challenge=b"recovery-challenge")

        with patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ENABLE_ADMIN_WEBAUTHN_RECOVERY",
            True,
        ), patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
            "different-admin@example.com",
        ), patch(
            "app.api.routes.webauthn.decode_admin_webauthn_recovery_token",
            return_value={"user_id": user.id, "jti": "recovery-jti"},
        ), patch(
            "app.api.routes.webauthn.get_admin_webauthn_recovery_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.generate_registration_options",
            return_value=options,
        ), patch(
            "app.api.routes.webauthn.options_to_json",
            return_value='{"challenge":"abc","rp":{"name":"Test"}}',
        ), patch(
            "app.api.routes.webauthn._set_redis_challenge",
            new=AsyncMock(),
        ) as set_redis_mock:
            response = await webauthn_recovery_register_begin(
                Request(build_request()),
                WebAuthnRecoveryRegisterBeginRequest(recovery_token="recovery-token"),
                db=db,
            )

        set_redis_mock.assert_awaited_once_with("webauthn:reg_challenge:", str(user.id), options.challenge)
        self.assertEqual(response.options, {"challenge": "abc", "rp": {"name": "Test"}})

    async def test_recovery_register_complete_consumes_recovery_token_after_persisting_key(self):
        user = build_user(52)
        user.staff_permission = StaffPermission(id=16, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        db = FakeWebAuthnRecoveryDB(user=user, existing_credential=None)

        with patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ENABLE_ADMIN_WEBAUTHN_RECOVERY",
            True,
        ), patch.object(
            __import__("app.api.routes.webauthn", fromlist=["settings"]).settings,
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER",
            user.email,
        ), patch(
            "app.api.routes.webauthn.decode_admin_webauthn_recovery_token",
            return_value={"user_id": user.id, "jti": "recovery-jti"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(return_value=b"challenge"),
        ), patch(
            "app.api.routes.webauthn.parse_registration_credential_json",
            return_value=SimpleNamespace(),
        ), patch(
            "app.api.routes.webauthn.verify_registration_response",
            return_value=SimpleNamespace(
                credential_id=b"cred-52",
                credential_public_key=b"public-key",
                sign_count=3,
            ),
        ), patch(
            "app.api.routes.webauthn.consume_admin_webauthn_recovery_user_id",
            new=AsyncMock(return_value=user.id),
        ) as consume_recovery_mock, patch(
            "app.api.routes.webauthn.write_audit_log",
            new=AsyncMock(),
        ):
            response = await webauthn_recovery_register_complete(
                WebAuthnRecoveryRegisterCompleteRequest(
                    recovery_token="recovery-token",
                    credential={"id": "ignored"},
                    name="Recovered key",
                ),
                request=Request(build_request()),
                db=db,
            )

        consume_recovery_mock.assert_awaited_once_with("recovery-jti")
        self.assertEqual(response.name, "Recovered key")
        self.assertEqual(len(db.added), 1)
        persisted = db.added[0]
        self.assertEqual(persisted.user_id, user.id)
        self.assertEqual(persisted.name, "Recovered key")
        self.assertIsNotNone(persisted.created_at.tzinfo)
        self.assertEqual(persisted.created_at.tzinfo, UTC)

    def test_webauthn_credential_model_uses_timezone_aware_timestamps(self):
        self.assertTrue(WebAuthnCredential.__table__.c.created_at.type.timezone)
        self.assertTrue(WebAuthnCredential.__table__.c.last_used_at.type.timezone)

    async def test_webauthn_completion_uses_staff_permissions_without_minting_admin_claims(self):
        user = build_user(1)
        user.staff_permission = StaffPermission(id=10, user_id=user.id, role=StaffRole.SUPER_ADMIN, can_manage_moderators=True)
        credential = WebAuthnCredential(
            id=20,
            user_id=user.id,
            credential_id=b"cred-1",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDB(user, credential)
        body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"id": base64.urlsafe_b64encode(b"cred-1").decode().rstrip("="), "response": {}},
        )

        token_payload = {}

        def fake_create_access_token(*, data):
            token_payload.update(data)
            return "access-token"

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": user.id, "jti": "jti-1"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge", new=AsyncMock(return_value=b"challenge")
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=7),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ), patch(
            "app.api.routes.webauthn.create_access_token", side_effect=fake_create_access_token
        ):
            result = await webauthn_auth_complete(
                body,
                request=Request(build_request()),
                response=Response(),
                db=db,
            )

        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(token_payload["sub"], str(user.id))
        self.assertNotIn("admin_role", token_payload)
        self.assertNotIn("is_admin", token_payload)

    async def test_webauthn_completion_does_not_fall_back_to_legacy_admin_columns(self):
        user = build_user(2)
        user.staff_permission = None
        credential = WebAuthnCredential(
            id=21,
            user_id=user.id,
            credential_id=b"cred-2",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDB(user, credential)
        body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"rawId": base64.urlsafe_b64encode(b"cred-2").decode().rstrip("="), "response": {}},
        )

        token_payload = {}

        def fake_create_access_token(*, data):
            token_payload.update(data)
            return "access-token"

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": user.id, "jti": "jti-2"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge", new=AsyncMock(return_value=b"challenge")
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=9),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ), patch(
            "app.api.routes.webauthn.create_access_token", side_effect=fake_create_access_token
        ):
            result = await webauthn_auth_complete(
                body,
                request=Request(build_request()),
                response=Response(),
                db=db,
            )

        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(token_payload["sub"], str(user.id))
        self.assertNotIn("is_admin", token_payload)
        self.assertNotIn("admin_role", token_payload)

    async def test_same_challenge_replay_is_rejected(self):
        user = build_user(3)
        user.staff_permission = None
        credential = WebAuthnCredential(
            id=22,
            user_id=user.id,
            credential_id=b"cred-3",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDB(user, credential)
        body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"rawId": base64.urlsafe_b64encode(b"cred-3").decode().rstrip("="), "response": {}},
        )

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": user.id, "jti": "jti-3"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(side_effect=[b"challenge", None]),
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=11),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ):
            first = await webauthn_auth_complete(
                body,
                request=Request(build_request()),
                response=Response(),
                db=db,
            )
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_auth_complete(
                    body,
                    request=Request(build_request()),
                    response=Response(),
                    db=db,
                )

        self.assertEqual(first["token_type"], "bearer")
        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(
            exc_info.exception.detail,
            "Authentication challenge not found or expired. Please start over.",
        )

    async def test_concurrent_double_complete_allows_only_one_success(self):
        user = build_user(4)
        user.staff_permission = None
        credential = WebAuthnCredential(
            id=23,
            user_id=user.id,
            credential_id=b"cred-4",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDB(user, credential)
        body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"rawId": base64.urlsafe_b64encode(b"cred-4").decode().rstrip("="), "response": {}},
        )

        challenge_available = True

        async def consume_once(prefix: str, key: str):
            nonlocal challenge_available
            if challenge_available:
                challenge_available = False
                await asyncio.sleep(0.05)
                return b"challenge"
            return None

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": user.id, "jti": "jti-4"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=consume_once,
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=AsyncMock(return_value=user.id),
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=13),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ):
            results = await asyncio.gather(
                webauthn_auth_complete(
                    body,
                    request=Request(build_request()),
                    response=Response(),
                    db=db,
                ),
                webauthn_auth_complete(
                    body,
                    request=Request(build_request()),
                    response=Response(),
                    db=db,
                ),
                return_exceptions=True,
            )

        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].status_code, 400)
        self.assertEqual(
            failures[0].detail,
            "Authentication challenge not found or expired. Please start over.",
        )

    async def test_expired_pending_token_is_rejected_at_begin(self):
        credential = WebAuthnCredential(
            id=24,
            user_id=5,
            credential_id=b"cred-5",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnBeginDB([credential])
        body = WebAuthnAuthBeginRequest(mfa_session_token="expired-token")

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": 5, "jti": "expired-jti"},
        ), patch(
            "app.api.routes.webauthn.get_mfa_pending_user_id",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_auth_begin(Request(build_request()), body, db=db)

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(exc_info.exception.detail, "MFA session expired or already used")

    async def test_old_pending_artifact_is_invalid_after_success(self):
        user = build_user(6)
        user.staff_permission = None
        credential = WebAuthnCredential(
            id=25,
            user_id=user.id,
            credential_id=b"cred-6",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.utcnow(),
        )
        complete_db = FakeWebAuthnDB(user, credential)
        begin_db = FakeWebAuthnBeginDB([credential])
        complete_body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"rawId": base64.urlsafe_b64encode(b"cred-6").decode().rstrip("="), "response": {}},
        )
        begin_body = WebAuthnAuthBeginRequest(mfa_session_token="mfa-token")
        pending = {"jti-6": user.id}

        async def fake_get_pending(jti: str):
            return pending.get(jti)

        async def fake_consume_pending(jti: str):
            return pending.pop(jti, None)

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": user.id, "jti": "jti-6"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(return_value=b"challenge"),
        ), patch(
            "app.api.routes.webauthn.get_mfa_pending_user_id",
            new=fake_get_pending,
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=fake_consume_pending,
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=15),
        ), patch(
            "app.api.routes.webauthn.generate_authentication_options",
            return_value=SimpleNamespace(challenge=b"next-challenge"),
        ), patch(
            "app.api.routes.webauthn.options_to_json",
            return_value='{"challenge": "next"}',
        ), patch(
            "app.api.routes.webauthn._set_redis_challenge",
            new=AsyncMock(),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ):
            result = await webauthn_auth_complete(
                complete_body,
                request=Request(build_request()),
                response=Response(),
                db=complete_db,
            )
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_auth_begin(Request(build_request()), begin_body, db=begin_db)

        self.assertEqual(result["token_type"], "bearer")
        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(exc_info.exception.detail, "MFA session expired or already used")

    async def test_register_complete_rejects_duplicate_credential_for_same_user(self):
        user = build_user(7)
        existing = WebAuthnCredential(
            id=70,
            user_id=user.id,
            credential_id=b"cred-7",
            public_key=b"public-key",
            sign_count=1,
            name="Existing key",
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnRegisterDB(existing_credential=existing)
        body = WebAuthnRegisterCompleteRequest(
            credential={"id": "ignored"},
            name="New key",
        )

        with patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(return_value=b"challenge"),
        ), patch(
            "app.api.routes.webauthn.parse_registration_credential_json",
            return_value=SimpleNamespace(),
        ), patch(
            "app.api.routes.webauthn.verify_registration_response",
            return_value=SimpleNamespace(
                credential_id=b"cred-7",
                credential_public_key=b"public-key",
                sign_count=9,
            ),
        ):
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_register_complete(
                    body,
                    request=Request(build_request()),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(exc_info.exception.status_code, 409)
        self.assertEqual(exc_info.exception.detail, "This security key is already registered to your account")

    async def test_register_complete_rejects_duplicate_credential_for_other_user_without_leak(self):
        user = build_user(8)
        existing = WebAuthnCredential(
            id=80,
            user_id=999,
            credential_id=b"cred-8",
            public_key=b"public-key",
            sign_count=1,
            name="Existing key",
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnRegisterDB(existing_credential=existing)
        body = WebAuthnRegisterCompleteRequest(
            credential={"id": "ignored"},
            name="New key",
        )

        with patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(return_value=b"challenge"),
        ), patch(
            "app.api.routes.webauthn.parse_registration_credential_json",
            return_value=SimpleNamespace(),
        ), patch(
            "app.api.routes.webauthn.verify_registration_response",
            return_value=SimpleNamespace(
                credential_id=b"cred-8",
                credential_public_key=b"public-key",
                sign_count=9,
            ),
        ):
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_register_complete(
                    body,
                    request=Request(build_request()),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(exc_info.exception.status_code, 409)
        self.assertEqual(exc_info.exception.detail, "This security key is already registered")

    async def test_register_complete_converts_integrity_error_into_conflict(self):
        user = build_user(9)
        db = FakeWebAuthnRegisterDB(fail_commit=True)
        body = WebAuthnRegisterCompleteRequest(
            credential={"id": "ignored"},
            name="Race key",
        )

        with patch(
            "app.api.routes.webauthn._consume_redis_challenge",
            new=AsyncMock(return_value=b"challenge"),
        ), patch(
            "app.api.routes.webauthn.parse_registration_credential_json",
            return_value=SimpleNamespace(),
        ), patch(
            "app.api.routes.webauthn.verify_registration_response",
            return_value=SimpleNamespace(
                credential_id=b"cred-9",
                credential_public_key=b"public-key",
                sign_count=9,
            ),
        ), patch(
            "app.api.routes.webauthn.write_audit_log",
            new=AsyncMock(),
        ):
            with self.assertRaises(HTTPException) as exc_info:
                await webauthn_register_complete(
                    body,
                    request=Request(build_request()),
                    current_user=user,
                    db=db,
                )

        self.assertTrue(db.rollback_called)
        self.assertEqual(exc_info.exception.status_code, 409)
        self.assertEqual(exc_info.exception.detail, "This security key is already registered")

    async def test_delete_credential_requires_password_after_ownership_check(self):
        user = build_user(10)
        user.password_hash = "hashed-password"
        credential = WebAuthnCredential(
            id=100,
            user_id=user.id,
            credential_id=b"cred-10",
            public_key=b"public-key",
            sign_count=1,
            name="Laptop key",
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDeleteDB(owned_credential=credential, user_credentials=[credential])

        with self.assertRaises(HTTPException) as exc_info:
            await delete_webauthn_credential(
                credential.id,
                WebAuthnCredentialDeleteRequest(current_password=None),
                request=build_delete_request(),
                current_user=user,
                db=db,
            )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Current password required to remove security key")

    async def test_delete_credential_rejects_wrong_password(self):
        user = build_user(11)
        user.password_hash = "hashed-password"
        credential = WebAuthnCredential(
            id=110,
            user_id=user.id,
            credential_id=b"cred-11",
            public_key=b"public-key",
            sign_count=1,
            name="Phone key",
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDeleteDB(owned_credential=credential, user_credentials=[credential])

        with patch("app.api.routes.webauthn.verify_password", return_value=False):
            with self.assertRaises(HTTPException) as exc_info:
                await delete_webauthn_credential(
                    credential.id,
                    WebAuthnCredentialDeleteRequest(current_password="wrong"),
                    request=build_delete_request(),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Current password is incorrect")

    async def test_delete_credential_denies_privileged_last_key(self):
        user = build_user(12)
        user.password_hash = "hashed-password"
        user.staff_permission = StaffPermission(id=12, user_id=user.id, role=StaffRole.ADMIN)
        credential = WebAuthnCredential(
            id=120,
            user_id=user.id,
            credential_id=b"cred-12",
            public_key=b"public-key",
            sign_count=1,
            name="Only key",
            created_at=datetime.utcnow(),
        )
        db = FakeWebAuthnDeleteDB(owned_credential=credential, user_credentials=[credential])

        with patch("app.api.routes.webauthn.verify_password", return_value=True):
            with self.assertRaises(HTTPException) as exc_info:
                await delete_webauthn_credential(
                    credential.id,
                    WebAuthnCredentialDeleteRequest(current_password="correct"),
                    request=build_delete_request(),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(
            exc_info.exception.detail,
            "Privileged accounts must retain at least one security key. Register a replacement key before removing this one.",
        )

    async def test_delete_credential_revokes_active_refresh_sessions_after_success(self):
        user = build_user(13)
        user.password_hash = "hashed-password"
        first_credential = WebAuthnCredential(
            id=130,
            user_id=user.id,
            credential_id=b"cred-13",
            public_key=b"public-key",
            sign_count=1,
            name="Phone key",
            created_at=datetime.utcnow(),
        )
        second_credential = WebAuthnCredential(
            id=131,
            user_id=user.id,
            credential_id=b"cred-13b",
            public_key=b"public-key",
            sign_count=1,
            name="Backup key",
            created_at=datetime.utcnow(),
        )
        refresh_tokens = [
            RefreshToken(id=1, user_id=user.id, token_hash="a", expires_at=datetime.utcnow(), revoked=False),
            RefreshToken(id=2, user_id=user.id, token_hash="b", expires_at=datetime.utcnow(), revoked=False),
        ]
        db = FakeWebAuthnDeleteDB(
            owned_credential=first_credential,
            user_credentials=[first_credential, second_credential],
            refresh_tokens=refresh_tokens,
        )

        with patch("app.api.routes.webauthn.verify_password", return_value=True), patch(
            "app.api.routes.webauthn.write_audit_log",
            new=AsyncMock(),
        ) as audit_log:
            response = await delete_webauthn_credential(
                first_credential.id,
                WebAuthnCredentialDeleteRequest(current_password="correct"),
                request=build_delete_request(),
                current_user=user,
                db=db,
            )

        self.assertIsNone(response)
        self.assertEqual(db.deleted, [first_credential])
        self.assertTrue(all(token.revoked for token in refresh_tokens))
        self.assertEqual(audit_log.await_args.kwargs["after"]["revoked_session_count"], 2)

    async def test_delete_credential_non_owner_stays_not_found_without_password_check(self):
        user = build_user(14)
        user.password_hash = "hashed-password"
        db = FakeWebAuthnDeleteDB(owned_credential=None, user_credentials=[])

        with patch("app.api.routes.webauthn.verify_password") as verify_password_mock:
            with self.assertRaises(HTTPException) as exc_info:
                await delete_webauthn_credential(
                    999,
                    WebAuthnCredentialDeleteRequest(current_password="correct"),
                    request=build_delete_request(),
                    current_user=user,
                    db=db,
                )

        verify_password_mock.assert_not_called()
        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.detail, "Security key not found")

    async def test_admin_list_webauthn_credentials_requires_super_admin(self):
        actor = build_user(20)
        actor.staff_permission = StaffPermission(id=20, user_id=actor.id, role=StaffRole.ADMIN)
        target = build_user(21)
        db = FakeAdminWebAuthnDB(target_user=target)

        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            with self.assertRaises(HTTPException) as exc_info:
                await list_user_webauthn_credentials(
                    request=build_admin_request("GET", f"/api/admin/users/{target.id}/webauthn-credentials"),
                    user_id=target.id,
                    db=db,
                    current_admin=actor,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Insufficient permissions for this action")

    async def test_admin_list_webauthn_credentials_returns_safe_fingerprints(self):
        actor = build_user(22)
        actor.staff_permission = StaffPermission(id=22, user_id=actor.id, role=StaffRole.SUPER_ADMIN)
        target = build_user(23)
        first = WebAuthnCredential(
            id=230,
            user_id=target.id,
            credential_id=b"raw-credential-one",
            public_key=b"public-key",
            sign_count=1,
            name="Laptop key",
            created_at=datetime.utcnow(),
            last_used_at=datetime.utcnow(),
        )
        second = WebAuthnCredential(
            id=231,
            user_id=target.id,
            credential_id=b"raw-credential-two",
            public_key=b"public-key",
            sign_count=1,
            name="Backup key",
            created_at=datetime.utcnow(),
        )
        db = FakeAdminWebAuthnDB(target_user=target, credentials=[first, second])

        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            response = await list_user_webauthn_credentials(
                request=build_admin_request("GET", f"/api/admin/users/{target.id}/webauthn-credentials"),
                user_id=target.id,
                db=db,
                current_admin=actor,
            )

        self.assertEqual([item.id for item in response], [230, 231])
        self.assertEqual(response[0].credential_identifier[:9], "webauthn:")
        self.assertNotIn("raw-credential-one", response[0].credential_identifier)
        self.assertEqual(response[0].name, "Laptop key")

    async def test_admin_delete_webauthn_credential_revokes_sessions_and_writes_audit(self):
        actor = build_user(24)
        actor.staff_permission = StaffPermission(id=24, user_id=actor.id, role=StaffRole.SUPER_ADMIN)
        target = build_user(25)
        credential = WebAuthnCredential(
            id=250,
            user_id=target.id,
            credential_id=b"raw-credential-delete",
            public_key=b"public-key",
            sign_count=1,
            name="Lost key",
            created_at=datetime.utcnow(),
        )
        refresh_tokens = [
            RefreshToken(id=1, user_id=target.id, token_hash="a", expires_at=datetime.utcnow(), revoked=False),
            RefreshToken(id=2, user_id=target.id, token_hash="b", expires_at=datetime.utcnow(), revoked=False),
        ]
        db = FakeAdminWebAuthnDB(
            target_user=target,
            credential=credential,
            credentials=[credential],
            refresh_tokens=refresh_tokens,
        )

        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()), patch(
            "app.api.routes.admin.write_audit_log", new=AsyncMock()
        ) as audit_log:
            response = await delete_user_webauthn_credential(
                request=build_admin_request("DELETE", f"/api/admin/users/{target.id}/webauthn-credentials/{credential.id}"),
                user_id=target.id,
                credential_id=credential.id,
                body=SensitiveAdminActionRequest(reason="Lost hardware key"),
                db=db,
                current_admin=actor,
            )

        self.assertIsNone(response)
        self.assertEqual(db.deleted, [credential])
        self.assertTrue(all(token.revoked for token in refresh_tokens))
        self.assertEqual(audit_log.await_args.kwargs["action"], "webauthn.admin_key_removed")
        self.assertEqual(
            audit_log.await_args.kwargs["after"],
            {"credential_db_id": credential.id, "key_name": credential.name},
        )

    async def test_admin_delete_webauthn_credential_returns_404_when_user_missing(self):
        actor = build_user(26)
        actor.staff_permission = StaffPermission(id=26, user_id=actor.id, role=StaffRole.SUPER_ADMIN)
        db = FakeAdminWebAuthnDB(target_user=None)

        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            with self.assertRaises(HTTPException) as exc_info:
                await delete_user_webauthn_credential(
                    request=build_admin_request("DELETE", "/api/admin/users/999/webauthn-credentials/1"),
                    user_id=999,
                    credential_id=1,
                    body=SensitiveAdminActionRequest(reason="Lost hardware key"),
                    db=db,
                    current_admin=actor,
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.detail, "User not found")

    async def test_admin_delete_webauthn_credential_returns_404_when_credential_missing(self):
        actor = build_user(27)
        actor.staff_permission = StaffPermission(id=27, user_id=actor.id, role=StaffRole.SUPER_ADMIN)
        target = build_user(28)
        db = FakeAdminWebAuthnDB(target_user=target, credential=None, credentials=[])

        with patch("app.api.routes.admin.enforce_rate_limits", new=AsyncMock()):
            with self.assertRaises(HTTPException) as exc_info:
                await delete_user_webauthn_credential(
                    request=build_admin_request("DELETE", f"/api/admin/users/{target.id}/webauthn-credentials/999"),
                    user_id=target.id,
                    credential_id=999,
                    body=SensitiveAdminActionRequest(reason="Lost hardware key"),
                    db=db,
                    current_admin=actor,
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.detail, "Security key not found")


if __name__ == "__main__":
    unittest.main()
