import base64
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db, require_admin_session
from app.api.routes.admin_staff import create_staff_assignment
from app.api.routes.auth import refresh_token
from app.api.routes.webauthn import webauthn_auth_complete
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential
from app.schemas.auth import RefreshTokenRequest
from app.schemas.staff import StaffAssignmentCreate
from app.schemas.webauthn import WebAuthnAuthCompleteRequest


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalar(self):
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


def build_user(user_id: int, username: str, *, verified: bool = True) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        password_hash="$2b$12$wbrx8rE2RFeQW5Q0imeISuB4EZ8ailqXF/w3vGN9VOGBev5Firefox",  # unused in direct-call tests
        created_at=datetime.now(timezone.utc),
        is_active=True,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
    )


def build_request(path: str, *, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers or [],
        }
    )


class SecurityClosureDB:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.webauthn_credentials: list[WebAuthnCredential] = []
        self.refresh_tokens: list[RefreshToken] = []
        self.staff_permission: StaffPermission | None = None

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        statement_text = " ".join(str(statement).split())
        statement_text_lower = statement_text.lower()
        params = statement.compile().params

        def _first_int_param():
            return next((value for value in params.values() if isinstance(value, int) and not isinstance(value, bool)), None)

        if entity is User:
            if "where users.username =" in statement_text_lower:
                username = next((value for value in params.values() if isinstance(value, str)), None)
                user = next((item for item in self.users.values() if item.username == username), None)
                return _ScalarResult(user)
            user_id = _first_int_param()
            return _ScalarResult(self.users.get(user_id))

        if entity is WebAuthnCredential:
            user_id = params.get("user_id_1")
            credential_id = params.get("credential_id_1")
            if credential_id is not None:
                cred = next(
                    (
                        item
                        for item in self.webauthn_credentials
                        if item.user_id == user_id and item.credential_id == credential_id
                    ),
                    None,
                )
                return _ScalarResult(cred)
            cred = next((item for item in self.webauthn_credentials if item.user_id == user_id), None)
            return _ScalarResult(cred)

        if entity is RefreshToken:
            if "where refresh_tokens.token_hash =" in statement_text_lower:
                token_hash = next((value for value in params.values() if isinstance(value, str)), None)
                token = next((item for item in self.refresh_tokens if item.token_hash == token_hash), None)
                return _ScalarResult(token)
            if "where refresh_tokens.id =" in statement_text_lower:
                token_id = _first_int_param()
                token = next((item for item in self.refresh_tokens if item.id == token_id), None)
                return _ScalarResult(token)
            if "where refresh_tokens.user_id =" in statement_text_lower:
                user_id = _first_int_param()
                tokens = [item for item in self.refresh_tokens if item.user_id == user_id]
                if "refresh_tokens.revoked = false" in statement_text_lower:
                    tokens = [item for item in tokens if not item.revoked]
                return _ListResult(tokens)
            raise AssertionError(f"Unhandled refresh token query: {statement_text}")

        if entity is StaffPermission:
            if "where staff_permissions.id =" in statement_text_lower:
                permission_id = _first_int_param()
                if self.staff_permission is not None and self.staff_permission.id == permission_id:
                    return _ScalarResult(self.staff_permission)
                return _ScalarResult(None)
            if "from staff_permissions" in statement_text_lower:
                values = [self.staff_permission] if self.staff_permission is not None else []
                return _ListResult(values)

        raise AssertionError(f"Unexpected entity {entity}")

    def add(self, instance):
        if isinstance(instance, RefreshToken):
            self.refresh_tokens.append(instance)
        elif isinstance(instance, StaffPermission):
            self.staff_permission = instance
            user = self.users.get(instance.user_id)
            if user is not None:
                user.staff_permission = instance
                instance.user = user

    async def flush(self):
        for index, token in enumerate(self.refresh_tokens, start=1):
            if token.id is None:
                token.id = index
        if self.staff_permission is not None and self.staff_permission.id is None:
            self.staff_permission.id = 500
        if self.staff_permission is not None and self.staff_permission.created_at is None:
            self.staff_permission.created_at = datetime.now(timezone.utc)
        if self.staff_permission is not None and self.staff_permission.updated_at is None:
            self.staff_permission.updated_at = datetime.now(timezone.utc)

    async def commit(self):
        return None

    async def delete(self, instance):
        if instance is self.staff_permission:
            user = self.users.get(instance.user_id)
            if user is not None:
                user.staff_permission = None
            self.staff_permission = None


class SessionAssuranceTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.db = SecurityClosureDB()

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

    def test_password_only_login_creates_session_with_mfa_satisfied_false(self):
        from app.core.security import get_password_hash

        user = build_user(1, "plainuser")
        user.password_hash = get_password_hash("Str0ng!Pass1")
        self.db.users[user.id] = user

        with patch("app.api.routes.auth.create_access_token", return_value="access-token"), patch(
            "app.api.routes.auth.create_refresh_token",
            return_value="refresh-token-1",
        ):
            response = self._client().post(
                "/api/auth/login",
                json={"username": user.username, "password": "Str0ng!Pass1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.db.refresh_tokens), 1)
        self.assertFalse(self.db.refresh_tokens[0].mfa_satisfied)


class PrivilegedSessionSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.dependency_overrides.clear()
        self.db = SecurityClosureDB()

    async def asyncTearDown(self):
        app.dependency_overrides.clear()

    async def test_webauthn_complete_login_creates_session_with_mfa_satisfied_true(self):
        user = build_user(2, "mfauser")
        self.db.users[user.id] = user
        credential = WebAuthnCredential(
            id=20,
            user_id=user.id,
            credential_id=b"cred-2",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.now(timezone.utc),
        )
        self.db.webauthn_credentials.append(credential)
        body = WebAuthnAuthCompleteRequest(
            mfa_session_token="mfa-token",
            credential={"rawId": base64.urlsafe_b64encode(b"cred-2").decode().rstrip("="), "response": {}},
        )

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
            return_value=SimpleNamespace(new_sign_count=7),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ), patch(
            "app.api.routes.webauthn.create_access_token", return_value="access-token"
        ), patch(
            "app.api.routes.webauthn.create_refresh_token", return_value="refresh-token-2"
        ), patch(
            "app.api.routes.webauthn.enforce_rate_limits", new=AsyncMock()
        ):
            result = await webauthn_auth_complete(
                body,
                request=build_request(
                    "/api/webauthn/auth/complete",
                    headers=[
                        (b"user-agent", b"pytest"),
                        (b"accept-language", b"en-US"),
                        (b"accept-encoding", b"gzip"),
                        (b"sec-ch-ua-platform", b"macOS"),
                    ],
                ),
                response=Response(),
                db=self.db,
            )

        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(len(self.db.refresh_tokens), 1)
        self.assertTrue(self.db.refresh_tokens[0].mfa_satisfied)

    async def test_refresh_carries_forward_mfa_satisfied(self):
        user = build_user(3, "rotateuser")
        self.db.users[user.id] = user
        session = RefreshToken(
            id=10,
            user_id=user.id,
            token_hash="hashed-old-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            revoked=False,
            mfa_satisfied=True,
            created_at=datetime.now(timezone.utc),
            last_used_at=datetime.now(timezone.utc),
            device_fingerprint="device-fp",
        )
        self.db.refresh_tokens.append(session)

        with patch("app.api.routes.auth.hash_refresh_token", side_effect=lambda raw: f"hashed-{raw}"), patch(
            "app.api.routes.auth._get_device_fingerprint",
            return_value="device-fp",
        ), patch(
            "app.api.routes.auth.create_refresh_token",
            return_value="new-refresh",
        ), patch("app.api.routes.auth.create_access_token", return_value="access-token"), patch(
            "app.api.routes.auth.write_audit_log",
            new=AsyncMock(),
        ), patch("app.api.routes.auth.enforce_rate_limits", new=AsyncMock()):
            result = await refresh_token(
                RefreshTokenRequest(refresh_token="old-refresh"),
                request=build_request("/api/auth/refresh", headers=[(b"user-agent", b""), (b"accept-language", b""), (b"accept-encoding", b""), (b"sec-ch-ua-platform", b"")]),
                response=Response(),
                db=self.db,
            )

        self.assertEqual(result.access_token, "access-token")
        self.assertTrue(session.revoked)
        self.assertEqual(len(self.db.refresh_tokens), 2)
        self.assertTrue(self.db.refresh_tokens[-1].mfa_satisfied)

    async def test_non_staff_user_cannot_access_admin_route(self):
        user = build_user(4, "nonstaff")
        self.db.users[user.id] = user
        self.db.refresh_tokens.append(
            RefreshToken(
                id=41,
                user_id=user.id,
                token_hash="hash-41",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                revoked=False,
                mfa_satisfied=True,
            )
        )

        with patch("app.api.deps.jwt.decode", return_value={"sub": "4", "username": "nonstaff", "sid": "41", "exp": 9999999999}):
            with self.assertRaises(HTTPException) as exc_info:
                await require_admin_session(
                    credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
                    db=self.db,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Admin session required")

    async def test_staff_user_with_mfa_satisfied_false_cannot_access_admin_route(self):
        user = build_user(5, "staff-low")
        user.staff_permission = StaffPermission(id=55, user_id=user.id, role=StaffRole.ADMIN, can_manage_moderators=True)
        self.db.users[user.id] = user
        self.db.webauthn_credentials.append(
            WebAuthnCredential(
                id=500,
                user_id=user.id,
                credential_id=b"cred-staff-low",
                public_key=b"pub-key",
                sign_count=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.refresh_tokens.append(
            RefreshToken(
                id=51,
                user_id=user.id,
                token_hash="hash-51",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                revoked=False,
                mfa_satisfied=False,
            )
        )

        with patch("app.api.deps.jwt.decode", return_value={"sub": "5", "username": "staff-low", "sid": "51", "exp": 9999999999}):
            with self.assertRaises(HTTPException) as exc_info:
                await require_admin_session(
                    credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
                    db=self.db,
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "Admin session requires MFA authentication")

    async def test_staff_user_with_mfa_satisfied_true_can_access_admin_route(self):
        user = build_user(6, "staff-high")
        user.staff_permission = StaffPermission(id=66, user_id=user.id, role=StaffRole.ADMIN, can_manage_moderators=True)
        self.db.users[user.id] = user
        self.db.refresh_tokens.append(
            RefreshToken(
                id=61,
                user_id=user.id,
                token_hash="hash-61",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                revoked=False,
                mfa_satisfied=True,
            )
        )

        with patch("app.api.deps.jwt.decode", return_value={"sub": "6", "username": "staff-high", "sid": "61", "exp": 9999999999}):
            result = await require_admin_session(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
                db=self.db,
            )

        self.assertEqual(result.id, user.id)

    async def test_non_session_bearer_token_is_rejected_cleanly_for_admin_routes(self):
        user = build_user(16, "staff-nosession")
        user.staff_permission = StaffPermission(id=166, user_id=user.id, role=StaffRole.ADMIN, can_manage_moderators=True)
        self.db.users[user.id] = user

        with patch("app.api.deps.jwt.decode", return_value={"sub": "16", "username": "staff-nosession", "exp": 9999999999}):
            with self.assertRaises(HTTPException) as exc_info:
                await require_admin_session(
                    credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="recovery-token"),
                    db=self.db,
                )

        self.assertEqual(exc_info.exception.status_code, 401)
        self.assertEqual(exc_info.exception.detail, "Could not validate credentials")

    async def test_staff_promotion_revokes_old_session_chain_until_relogin_with_mfa(self):
        target_user = build_user(7, "candidate")
        low_assurance_session = RefreshToken(
            id=71,
            user_id=target_user.id,
            token_hash="hashed-old-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            revoked=False,
            mfa_satisfied=False,
            created_at=datetime.now(timezone.utc),
            last_used_at=datetime.now(timezone.utc),
            device_fingerprint="device-fp",
        )
        self.db.users[target_user.id] = target_user
        self.db.refresh_tokens.append(low_assurance_session)
        current_admin = build_user(99, "superadmin")
        current_admin.staff_permission = StaffPermission(
            id=199,
            user_id=current_admin.id,
            role=StaffRole.SUPER_ADMIN,
            can_manage_moderators=True,
        )

        with patch("app.api.routes.admin_staff.write_audit_log", new=AsyncMock()):
            response = await create_staff_assignment(
                request=build_request("/api/admin/staff"),
                payload=StaffAssignmentCreate(username="candidate", role=StaffRole.MODERATOR, permissions=None, user_id=None),
                db=self.db,
                current_admin=current_admin,
            )

        self.assertEqual(response.user.user_id, target_user.id)
        self.assertTrue(low_assurance_session.revoked)

        with patch("app.api.deps.jwt.decode", return_value={"sub": "7", "username": "candidate", "sid": "71", "exp": 9999999999}):
            with self.assertRaises(HTTPException) as access_exc:
                await require_admin_session(
                    credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="old-access"),
                    db=self.db,
                )
        self.assertEqual(access_exc.exception.status_code, 401)

        with patch("app.api.routes.auth.hash_refresh_token", side_effect=lambda raw: f"hashed-{raw}"), patch(
            "app.api.routes.auth._get_device_fingerprint",
            return_value="device-fp",
        ), patch(
            "app.api.routes.auth.write_audit_log",
            new=AsyncMock(),
        ), patch("app.api.routes.auth.enforce_rate_limits", new=AsyncMock()):
            with self.assertRaises(HTTPException) as refresh_exc:
                await refresh_token(
                    RefreshTokenRequest(refresh_token="old-refresh"),
                    request=build_request("/api/auth/refresh"),
                    response=Response(),
                    db=self.db,
                )
        self.assertEqual(refresh_exc.exception.status_code, 401)

        credential = WebAuthnCredential(
            id=72,
            user_id=target_user.id,
            credential_id=b"cred-7",
            public_key=b"public-key",
            sign_count=1,
            created_at=datetime.now(timezone.utc),
        )
        self.db.webauthn_credentials.append(credential)

        with patch(
            "app.api.routes.webauthn._require_mfa_token",
            return_value={"user_id": target_user.id, "jti": "jti-7"},
        ), patch(
            "app.api.routes.webauthn._consume_redis_challenge", new=AsyncMock(return_value=b"challenge")
        ), patch(
            "app.api.routes.webauthn.consume_mfa_pending_user_id",
            new=AsyncMock(return_value=target_user.id),
        ), patch(
            "app.api.routes.webauthn.parse_authentication_credential_json", return_value=SimpleNamespace()
        ), patch(
            "app.api.routes.webauthn.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=8),
        ), patch(
            "app.api.routes.webauthn.write_audit_log", new=AsyncMock()
        ), patch(
            "app.api.routes.webauthn.create_access_token", return_value="mfa-access"
        ), patch(
            "app.api.routes.webauthn.create_refresh_token", return_value="mfa-refresh"
        ), patch(
            "app.api.routes.webauthn.enforce_rate_limits", new=AsyncMock()
        ):
            await webauthn_auth_complete(
                WebAuthnAuthCompleteRequest(
                    mfa_session_token="mfa-token",
                    credential={"rawId": base64.urlsafe_b64encode(b"cred-7").decode().rstrip("="), "response": {}},
                ),
                request=build_request(
                    "/api/webauthn/auth/complete",
                    headers=[
                        (b"user-agent", b"pytest"),
                        (b"accept-language", b"en-US"),
                        (b"accept-encoding", b"gzip"),
                        (b"sec-ch-ua-platform", b"macOS"),
                    ],
                ),
                response=Response(),
                db=self.db,
            )

        new_session = self.db.refresh_tokens[-1]
        self.assertTrue(new_session.mfa_satisfied)
        with patch(
            "app.api.deps.jwt.decode",
            return_value={"sub": "7", "username": "candidate", "sid": str(new_session.id), "exp": 9999999999},
        ):
            result = await require_admin_session(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="new-access"),
                db=self.db,
            )

        self.assertEqual(result.id, target_user.id)


if __name__ == "__main__":
    unittest.main()
