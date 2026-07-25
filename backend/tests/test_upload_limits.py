import os
import secrets
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi import UploadFile
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from starlette.requests import Request

from app.api import deps
from app.core.config import settings
from app.core.http import RequestBodySizeLimitMiddleware
from app.core.rate_limit import _memory_rate_limiter
from app.core.upload_limits import PayloadTooLargeError, read_upload_within_limit, reject_by_content_length_hint
from app.main import app


def _make_upload_file(content: bytes, filename: str = "file.png") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content), headers={"content-type": "image/png"})


def _fake_request(content_length: str | None) -> Request:
    headers = {"content-length": content_length} if content_length is not None else {}
    scope = {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


class ReadUploadWithinLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_exactly_limit_bytes(self):
        content = b"a" * 100
        result = await read_upload_within_limit(_make_upload_file(content), limit=100)
        self.assertEqual(result, content)

    async def test_rejects_limit_plus_one_bytes_with_413_not_400(self):
        content = b"a" * 101
        with self.assertRaises(PayloadTooLargeError) as ctx:
            await read_upload_within_limit(_make_upload_file(content), limit=100)
        self.assertEqual(ctx.exception.status_code, 413)


class RejectByContentLengthHintTests(unittest.TestCase):
    def test_over_limit_header_raises_413(self):
        request = _fake_request("1000")
        with self.assertRaises(PayloadTooLargeError) as ctx:
            reject_by_content_length_hint(request, limit=100)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_absent_header_is_noop(self):
        request = _fake_request(None)
        reject_by_content_length_hint(request, limit=100)  # must not raise

    def test_understated_header_is_noop_here(self):
        # An understated Content-Length passes this cheap pre-check by design —
        # the real streamed-byte count is what the ASGI middleware/read helper
        # actually enforce, not this header alone.
        request = _fake_request("10")
        reject_by_content_length_hint(request, limit=100)  # must not raise


class RequestBodySizeLimitMiddlewareUnitTests(unittest.IsolatedAsyncioTestCase):
    """ASGI-level tests driving the middleware directly with a synthetic scope
    and a fake receive() generator — the only reliable way to simulate a
    missing or understated Content-Length, since a real HTTP client always
    computes it correctly."""

    def _scope(self, path: str, content_length: str | None) -> dict:
        headers = []
        if content_length is not None:
            headers.append((b"content-length", content_length.encode()))
        return {"type": "http", "path": path, "headers": headers}

    async def _run(
        self, path: str, content_length: str | None, chunks: list[bytes], limit: int,
        *, configured_path: str = "/api/posts/upload-image",
    ):
        app_calls: list[str] = []

        async def downstream(scope, receive, send):
            app_calls.append("started")
            total = 0
            while True:
                message = await receive()
                total += len(message.get("body", b""))
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = RequestBodySizeLimitMiddleware(downstream, path_limits={configured_path: limit})

        remaining = list(chunks)

        async def receive():
            if remaining:
                chunk = remaining.pop(0)
                return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages = []

        async def send(message):
            sent_messages.append(message)

        await middleware(self._scope(path, content_length), receive, send)
        return sent_messages

    async def test_no_content_length_header_still_413s_when_streamed_bytes_exceed_limit(self):
        chunks = [b"x" * 60, b"x" * 60]  # 120 bytes total, no Content-Length header at all
        messages = await self._run("/api/posts/upload-image", None, chunks, limit=100)
        statuses = [m["status"] for m in messages if m["type"] == "http.response.start"]
        self.assertEqual(statuses, [413])

    async def test_understated_content_length_still_413s_on_actual_streamed_bytes(self):
        chunks = [b"x" * 60, b"x" * 60]  # header lies and says 10, real stream is 120 bytes
        messages = await self._run("/api/posts/upload-image", "10", chunks, limit=100)
        statuses = [m["status"] for m in messages if m["type"] == "http.response.start"]
        self.assertEqual(statuses, [413])

    async def test_within_limit_passes_through(self):
        chunks = [b"x" * 50]
        messages = await self._run("/api/posts/upload-image", None, chunks, limit=100)
        statuses = [m["status"] for m in messages if m["type"] == "http.response.start"]
        self.assertEqual(statuses, [200])

    async def test_unconfigured_path_is_not_guarded(self):
        chunks = [b"x" * 10_000]
        messages = await self._run(
            "/api/some/other/route", None, chunks, limit=100, configured_path="/api/posts/upload-image"
        )
        # limit only applies to the configured path — this scope's path has no entry, so
        # path_limits.get() returns None and the request passes through untouched.
        statuses = [m["status"] for m in messages if m["type"] == "http.response.start"]
        self.assertEqual(statuses, [200])

    async def test_trailing_slash_still_matched_by_normalized_path(self):
        chunks = [b"x" * 60, b"x" * 60]
        messages = await self._run(
            "/api/posts/upload-image/", None, chunks, limit=100, configured_path="/api/posts/upload-image"
        )
        statuses = [m["status"] for m in messages if m["type"] == "http.response.start"]
        self.assertEqual(statuses, [413])

    async def test_response_already_started_never_double_responds(self):
        # If the downstream has already started its OWN response before the
        # guard trips, the guard must never send a second http.response.start
        # (an ASGI protocol violation) — it just lets the disconnect signal
        # stop the downstream, and silently discards anything the downstream
        # still tries to send afterward.
        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = RequestBodySizeLimitMiddleware(downstream, path_limits={"/x": 100})
        remaining = [b"x" * 60, b"x" * 60]

        async def receive():
            if remaining:
                chunk = remaining.pop(0)
                return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages = []

        async def send(message):
            sent_messages.append(message)

        await middleware({"type": "http", "path": "/x", "headers": []}, receive, send)

        starts = [m for m in sent_messages if m["type"] == "http.response.start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["status"], 200)  # the downstream's own response, not our 413
        bodies = [m for m in sent_messages if m["type"] == "http.response.body"]
        self.assertEqual(bodies, [])  # the downstream's later body send was correctly discarded


class UploadRoutesReal413Tests(unittest.TestCase):
    """Integration tests posting oversized bodies to the 4 real upload routes."""

    def setUp(self):
        app.dependency_overrides.clear()
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()

    def tearDown(self):
        app.dependency_overrides.clear()
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()

    def _client_with_user(self) -> TestClient:
        async def override_user():
            return SimpleNamespace(id=1, username="tester", avatar_url=None, cover_url=None)

        app.dependency_overrides[deps.get_current_user] = override_user
        app.dependency_overrides[deps.get_current_interactive_user] = override_user
        return TestClient(app, base_url="http://localhost")

    def _oversized_body_for(self, limit_attr: str) -> bytes:
        limit = getattr(settings, limit_attr)
        return b"0" * (limit + 1024)

    def test_avatar_upload_oversized_body_gets_413_and_never_saves(self):
        client = self._client_with_user()
        storage_mock = MagicMock()
        storage_mock.save_file = AsyncMock()
        with patch("app.api.routes.users.get_storage_provider", return_value=storage_mock):
            response = client.post(
                "/api/users/me/avatar",
                files={"file": ("big.png", self._oversized_body_for("AVATAR_UPLOAD_MAX_BYTES"), "image/png")},
            )
        self.assertEqual(response.status_code, 413)
        storage_mock.save_file.assert_not_called()

    def test_cover_upload_oversized_body_gets_413_and_never_saves(self):
        client = self._client_with_user()
        storage_mock = MagicMock()
        storage_mock.save_file = AsyncMock()
        with patch("app.api.routes.users.get_storage_provider", return_value=storage_mock):
            response = client.post(
                "/api/users/me/cover",
                files={"file": ("big.png", self._oversized_body_for("COVER_UPLOAD_MAX_BYTES"), "image/png")},
            )
        self.assertEqual(response.status_code, 413)
        storage_mock.save_file.assert_not_called()

    def test_post_image_upload_oversized_body_gets_413_and_never_saves(self):
        client = self._client_with_user()
        storage_mock = MagicMock()
        storage_mock.save_file = AsyncMock()
        with patch("app.api.routes.posts.get_storage_provider", return_value=storage_mock):
            response = client.post(
                "/api/posts/upload-image",
                files={"file": ("big.png", self._oversized_body_for("POST_IMAGE_UPLOAD_MAX_BYTES"), "image/png")},
            )
        self.assertEqual(response.status_code, 413)
        storage_mock.save_file.assert_not_called()

    def test_feedback_report_oversized_attachment_gets_413_and_never_saves(self):
        client = self._client_with_user()
        storage_mock = MagicMock()
        storage_mock.save_file = AsyncMock()
        with patch("app.api.routes.feedback.get_storage_provider", return_value=storage_mock), patch(
            "app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))
        ):
            response = client.post(
                "/api/feedback/report",
                data={"title": "Oversized", "description": "This attachment is too large for the configured limit."},
                files={
                    "attachment": (
                        "big.png",
                        self._oversized_body_for("FEEDBACK_ATTACHMENT_MAX_BYTES"),
                        "image/png",
                    )
                },
            )
        self.assertEqual(response.status_code, 413)
        storage_mock.save_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
