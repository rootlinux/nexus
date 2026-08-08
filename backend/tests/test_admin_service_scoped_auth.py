import os
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.post import Post
from app.models.user import User, UserStatus
from app.services.push_notifications import PushSendResult


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else [self._value]


class FakeAsyncSession:
    """Returns queued results for successive db.execute() calls, in order."""

    def __init__(self, results):
        self._results = list(results)
        self.deleted: list = []
        self.committed = False

    async def execute(self, _stmt):
        return _FakeResult(self._results.pop(0))

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass

    def add(self, _obj):
        pass


def build_user(user_id: int, username: str = "target") -> User:
    return User(
        id=user_id,
        username=username,
        display_name=username,
        email=f"{username}@example.com",
        status=UserStatus.ACTIVE,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def build_post(post_id: int, user_id: int) -> Post:
    return Post(id=post_id, user_id=user_id, content="hello", created_at=datetime.now(timezone.utc))


class AdminServiceScopedAuthTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self._original_tokens = {
            "SERVICE_TOKEN_READ": settings.SERVICE_TOKEN_READ,
            "SERVICE_TOKEN_NOTIFY": settings.SERVICE_TOKEN_NOTIFY,
            "SERVICE_TOKEN_DELETE": settings.SERVICE_TOKEN_DELETE,
        }
        settings.SERVICE_TOKEN_READ = "read-token"
        settings.SERVICE_TOKEN_NOTIFY = "notify-token"
        settings.SERVICE_TOKEN_DELETE = "delete-token"

    def tearDown(self):
        app.dependency_overrides.clear()
        for key, value in self._original_tokens.items():
            setattr(settings, key, value)

    def _client(self, results) -> TestClient:
        session = FakeAsyncSession(results)

        async def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        return TestClient(app, base_url="http://localhost")

    def test_read_endpoint_rejects_missing_token(self):
        client = self._client([[]])
        response = client.get("/api/admin/service/users")
        self.assertEqual(response.status_code, 403)

    def test_read_endpoint_rejects_delete_scoped_token(self):
        client = self._client([[]])
        response = client.get("/api/admin/service/users", headers={"X-Service-Token": "delete-token"})
        self.assertEqual(response.status_code, 403)

    def test_read_endpoint_accepts_read_scoped_token(self):
        client = self._client([[build_user(1)]])
        response = client.get("/api/admin/service/users", headers={"X-Service-Token": "read-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_read_endpoint_rejects_removed_legacy_admin_token(self):
        # The all-scopes ADMIN_SERVICE_TOKEN fallback was removed. Its value is now just
        # an unrecognised token on every endpoint, including the read one it used to open.
        client = self._client([[]])
        response = client.get("/api/admin/service/users", headers={"X-Service-Token": "legacy-token"})
        self.assertEqual(response.status_code, 403)

    def test_delete_user_rejects_read_scoped_token(self):
        client = self._client([build_user(2)])
        response = client.delete("/api/admin/service/users/2", headers={"X-Service-Token": "read-token"})
        self.assertEqual(response.status_code, 403)

    def test_delete_user_rejects_notify_scoped_token(self):
        client = self._client([build_user(2)])
        response = client.delete("/api/admin/service/users/2", headers={"X-Service-Token": "notify-token"})
        self.assertEqual(response.status_code, 403)

    def test_notify_endpoint_rejects_read_scoped_token(self):
        client = self._client([])
        response = client.post(
            "/api/admin/service/notifications/push",
            headers={"X-Service-Token": "read-token"},
            json={"user_id": "3", "title": "Hi", "body": "There"},
        )
        self.assertEqual(response.status_code, 403)

    def test_no_tokens_configured_leaves_service_endpoints_fail_closed(self):
        # No token configured for any scope at all: the app must still start and serve
        # requests normally — admin_service.* endpoints just always reject, rather than
        # the process refusing to boot (a hard startup requirement here would force every
        # deployment to configure a service token even if it never uses the integration).
        settings.SERVICE_TOKEN_READ = ""
        settings.SERVICE_TOKEN_NOTIFY = ""
        settings.SERVICE_TOKEN_DELETE = ""

        client = self._client([[]])
        self.assertEqual(
            client.get("/api/admin/service/users", headers={"X-Service-Token": "anything"}).status_code,
            403,
        )
        self.assertEqual(
            client.delete("/api/admin/service/users/1", headers={"X-Service-Token": "anything"}).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                "/api/admin/service/notifications/push",
                headers={"X-Service-Token": "anything"},
                json={"user_id": "1", "title": "Hi", "body": "There"},
            ).status_code,
            403,
        )

        # Public, unauthenticated endpoints are untouched by service-token configuration.
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/health").status_code, 200)

    def test_failed_authorization_is_logged_without_leaking_the_token(self):
        client = self._client([[]])
        with self.assertLogs("app.api.dependencies.service_auth", level="WARNING") as log_ctx:
            response = client.get(
                "/api/admin/service/users", headers={"X-Service-Token": "not-a-real-token"}
            )
        self.assertEqual(response.status_code, 403)
        log_output = "\n".join(log_ctx.output)
        self.assertIn("scope=service:read", log_output)
        self.assertNotIn("not-a-real-token", log_output)

    def test_delete_user_writes_audit_log_with_service_principal_and_no_raw_token(self):
        client = self._client([build_user(2)])
        audit_mock = AsyncMock()
        with patch("app.api.routes.admin_service.write_audit_log", audit_mock):
            response = client.delete("/api/admin/service/users/2", headers={"X-Service-Token": "delete-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "admin_service.delete_user")
        self.assertEqual(audit_mock.await_args.kwargs["actor_type"], "service")
        self.assertEqual(audit_mock.await_args.kwargs["service_principal_id"], "service-delete")
        self.assertEqual(audit_mock.await_args.kwargs["auth_scopes"], ["service:delete"])
        self.assertEqual(audit_mock.await_args.kwargs["target_type"], "user")
        self.assertEqual(audit_mock.await_args.kwargs["target_id"], 2)
        self.assertNotIn("delete-token", str(audit_mock.await_args.kwargs))

    def test_delete_post_writes_audit_log(self):
        client = self._client([build_post(5, user_id=2)])
        audit_mock = AsyncMock()
        with patch("app.api.routes.admin_service.write_audit_log", audit_mock):
            response = client.delete("/api/admin/service/posts/5", headers={"X-Service-Token": "delete-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "admin_service.delete_post")
        self.assertEqual(audit_mock.await_args.kwargs["target_id"], 5)

    def test_send_push_notification_requires_notify_scope_and_writes_audit_log(self):
        target = build_user(3)
        client = self._client([target, []])
        audit_mock = AsyncMock()
        push_result = PushSendResult(sent_count=1, failed_count=0)
        with (
            patch("app.api.routes.admin_service.write_audit_log", audit_mock),
            patch("app.api.routes.admin_service.web_push_is_configured", return_value=True),
            patch(
                "app.api.routes.admin_service.send_push_payload_to_user",
                AsyncMock(return_value=push_result),
            ),
        ):
            response = client.post(
                "/api/admin/service/notifications/push",
                headers={"X-Service-Token": "notify-token"},
                json={"user_id": "3", "title": "Hi", "body": "There"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(audit_mock.await_args.kwargs["action"], "admin_service.send_push_notification")
        self.assertEqual(audit_mock.await_args.kwargs["service_principal_id"], "service-notify")
        self.assertEqual(audit_mock.await_args.kwargs["after"]["sent_count"], 1)

    def test_send_push_notification_rejects_delete_scoped_token(self):
        client = self._client([])
        response = client.post(
            "/api/admin/service/notifications/push",
            headers={"X-Service-Token": "delete-token"},
            json={"user_id": "3", "title": "Hi", "body": "There"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
