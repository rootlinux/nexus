import asyncio
import json
import os
import secrets
import shutil
import stat
import tempfile
import unittest
from base64 import b64decode
from urllib.parse import urlparse
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.main import app
from app.api import deps
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import _memory_rate_limiter
from tests.media_test_support import create_test_user

SAMPLE_PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c/aAAAAAASUVORK5CYII=")


class FeedbackReportApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()
        self._original_feedback_to = settings.FEEDBACK_REPORT_TO_EMAIL
        self._original_mail_provider = settings.MAIL_PROVIDER
        self._original_mail_capture_dir = settings.MAIL_CAPTURE_DIR
        # Round 2, Task 1 fix: this test file submits real feedback attachments
        # through the real LocalStorageProvider (no storage mock), and
        # _get_feedback_storage_provider() reads settings.FEEDBACK_ATTACHMENT_LOCAL_DIR
        # fresh on every call. Left at its default, that resolves to the real,
        # protected backend/feedback_private_uploads/ directory whenever tests
        # run from backend/ — redirect it to an isolated temp directory for the
        # duration of each test instead.
        self._original_feedback_attachment_dir = settings.FEEDBACK_ATTACHMENT_LOCAL_DIR
        self._feedback_attachment_temp_dir = tempfile.mkdtemp(prefix="feedback-attachments-test-")
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self._feedback_attachment_temp_dir

        # Round 2 Task 3: submit_feedback_report now writes real FeedbackReport/
        # MediaAsset/UserMediaQuota rows (submitter_user_id/owner_user_id are real
        # FKs to users.id), so this needs a genuine DB-backed user and its own
        # dedicated engine/session — never the app's shared global get_db engine,
        # which collides across event loops with other test files sharing this
        # pytest process ("attached to a different loop", confirmed via a real
        # failure during Task 3's own full-suite verification run).
        # This engine is used ONLY by override_db(), inside whatever loop
        # TestClient's own requests actually run on. NullPool is required:
        # TestClient does not guarantee one persistent event loop across
        # separate .post()/.get() calls on the same instance (confirmed via
        # a real "Event loop is closed" failure on a test making 4 sequential
        # requests) — pooling a connection risks handing a later request a
        # connection bound to an already-closed prior loop. NullPool opens a
        # fresh physical connection per checkout and discards it afterward,
        # which is safe regardless of which loop is live for a given request.
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.test_user_id = asyncio.run(self._create_test_user_via_temp_engine())

    def tearDown(self):
        app.dependency_overrides.clear()
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()
        settings.FEEDBACK_REPORT_TO_EMAIL = self._original_feedback_to
        settings.MAIL_PROVIDER = self._original_mail_provider
        settings.MAIL_CAPTURE_DIR = self._original_mail_capture_dir
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self._original_feedback_attachment_dir
        shutil.rmtree(self._feedback_attachment_temp_dir, ignore_errors=True)
        asyncio.run(self.engine.dispose())

    async def _create_test_user_via_temp_engine(self) -> int:
        # A dedicated, fully-disposed-before-return engine — NOT self.engine.
        # asyncio.run() opens and closes its own event loop; if we drew this
        # connection from self.engine's pool instead, that pool would keep a
        # live connection bound to this now-closed loop, and TestClient's
        # later request (its own separate loop) would crash reusing it
        # ("attached to a different loop") — confirmed via a real failure
        # when this was first tried against self.engine directly.
        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_session_factory = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_session_factory() as session:
                user = await create_test_user(session)
                await session.commit()
                return user.id
        finally:
            await temp_engine.dispose()

    def _client(self) -> TestClient:
        async def override_user():
            return SimpleNamespace(
                id=self.test_user_id,
                username="lukey",
                email="lukey@example.com",
                status=None,
                is_active=True,
            )

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[deps.get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db
        return TestClient(app, base_url="http://localhost")

    def _override_admin_session(self) -> None:
        async def override_admin():
            return SimpleNamespace(
                id=7,
                username="staffer",
                email="staffer@example.com",
                status=None,
                is_active=True,
                staff_permission=SimpleNamespace(role="super_admin"),
            )

        app.dependency_overrides[deps.require_admin_session] = override_admin

    def test_feedback_report_sends_structured_email(self):
        with TemporaryDirectory() as temp_dir:
            settings.MAIL_PROVIDER = "capture"
            settings.MAIL_CAPTURE_DIR = temp_dir
            settings.FEEDBACK_REPORT_TO_EMAIL = "beta@example.com"

            with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
                client = self._client()
                response = client.post(
                    "/api/feedback/report",
                    json={
                        "title": "Feed froze after refresh",
                        "description": "The timeline stopped updating after I pulled to refresh in the installed app.",
                        "current_path": "/security",
                        "username": "lukey",
                        "device_info": "Safari 17 on iPhone, standalone PWA",
                        "contact_email": "reply@example.com",
                        "current_url": "https://lukeyz.app/security",
                        "user_agent": "Mozilla/5.0 test",
                        "standalone_mode": True,
                        "occurred_at": "2026-04-10T12:00:00.000Z",
                        "app_version": "web-2026.04.10",
                    },
                    headers={"user-agent": "Mozilla/5.0 fallback"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"message": "Your report was sent."})

            captured_files = list(Path(temp_dir).glob("*.json"))
            self.assertEqual(len(captured_files), 1)
            payload = captured_files[0].read_text(encoding="utf-8")
            self.assertIn('"to_email": "beta@example.com"', payload)
            self.assertIn("[Nexus] Feed froze after refresh", payload)
            self.assertIn("Safari 17 on iPhone, standalone PWA", payload)
            self.assertIn("reply@example.com", payload)
            self.assertIn("lukey@example.com", payload)
            self.assertIn("web-2026.04.10", payload)
            self.assertIn("Attachment: None", payload)

    def test_feedback_report_accepts_valid_attachment_and_includes_reference(self):
        with TemporaryDirectory() as temp_dir:
            settings.MAIL_PROVIDER = "capture"
            settings.MAIL_CAPTURE_DIR = temp_dir
            settings.FEEDBACK_REPORT_TO_EMAIL = "beta@example.com"
            with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
                client = self._client()
                response = client.post(
                    "/api/feedback/report",
                    data={
                        "title": "Screenshot helps",
                        "description": "The issue is easier to reproduce when you can see the frozen state in context.",
                    },
                    files={"attachment": ("frozen-feed.png", SAMPLE_PNG, "image/png")},
                )

            self.assertEqual(response.status_code, 200)
            captured_files = list(Path(temp_dir).glob("*.json"))
            self.assertEqual(len(captured_files), 1)
            payload = captured_files[0].read_text(encoding="utf-8")
            captured_message = json.loads(payload)
            self.assertIn("Attachment: Included", payload)
            self.assertIn("Attachment filename: frozen-feed.png", payload)
            self.assertIn("Attachment content type: image/png", payload)
            self.assertIn("Attachment URL: http://localhost/api/feedback/attachments/", payload)

            attachment_url = next(
                line.split("Attachment URL: ", 1)[1]
                for line in captured_message["text_body"].splitlines()
                if line.startswith("Attachment URL: ")
            )
            direct_path = urlparse(attachment_url).path

            unsigned_response = client.get(direct_path)
            self.assertEqual(unsigned_response.status_code, 401)
            self.assertEqual(unsigned_response.json(), {"detail": "Not authenticated"})

            self._override_admin_session()
            with patch("app.api.routes.feedback.enforce_rate_limits", new=AsyncMock()):
                signed_response = client.get(attachment_url)
            self.assertEqual(signed_response.status_code, 200)
            # Round 2, Task 2: the stored attachment is now decoded + re-encoded
            # (metadata stripping), so it is no longer byte-identical to the
            # original upload — assert it's still a valid, same-dimension PNG.
            from PIL import Image
            from io import BytesIO

            original = Image.open(BytesIO(SAMPLE_PNG))
            stored = Image.open(BytesIO(signed_response.content))
            self.assertEqual(stored.format, "PNG")
            self.assertEqual(stored.size, original.size)
            self.assertEqual(signed_response.headers["content-type"], "image/png")

    def test_feedback_attachment_signed_url_rejects_invalid_signature(self):
        with TemporaryDirectory() as temp_dir:
            settings.MAIL_PROVIDER = "capture"
            settings.MAIL_CAPTURE_DIR = temp_dir
            settings.FEEDBACK_REPORT_TO_EMAIL = "beta@example.com"
            with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
                client = self._client()
                response = client.post(
                    "/api/feedback/report",
                    data={
                        "title": "Screenshot helps",
                        "description": "The issue is easier to reproduce when you can see the frozen state in context.",
                    },
                    files={"attachment": ("frozen-feed.png", SAMPLE_PNG, "image/png")},
                )

            self.assertEqual(response.status_code, 200)
            payload = json.loads(next(Path(temp_dir).glob("*.json")).read_text(encoding="utf-8"))
            attachment_url = next(
                line.split("Attachment URL: ", 1)[1]
                for line in payload["text_body"].splitlines()
                if line.startswith("Attachment URL: ")
            )
            tampered_url = attachment_url.replace("sig=", "sig=bad")

            self._override_admin_session()
            with patch("app.api.routes.feedback.enforce_rate_limits", new=AsyncMock()):
                signed_response = client.get(tampered_url)
            self.assertEqual(signed_response.status_code, 403)
            self.assertEqual(signed_response.json(), {"detail": "Invalid attachment signature"})

    def test_feedback_report_rejects_invalid_attachment_type(self):
        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            client = self._client()
            response = client.post(
                "/api/feedback/report",
                data={
                    "title": "Wrong attachment type",
                    "description": "Trying to attach an unsupported file type should fail cleanly.",
                },
                files={"attachment": ("payload.svg", b"<svg></svg>", "image/svg+xml")},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Please attach a PNG, JPEG, or WebP image."})

    def test_feedback_report_rejects_oversized_attachment(self):
        oversized_png = SAMPLE_PNG + (b"0" * (settings.FEEDBACK_ATTACHMENT_MAX_BYTES + 1))

        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            client = self._client()
            response = client.post(
                "/api/feedback/report",
                data={
                    "title": "Too large attachment",
                    "description": "An oversized attachment should be blocked before it is stored.",
                },
                files={"attachment": ("oversized.png", oversized_png, "image/png")},
            )

        # Round 2, Task 1: oversize now short-circuits to 413 (via the ASGI body-size
        # guard / read_upload_within_limit) before assess_media_input/inspect_media_bytes
        # ever runs, instead of surfacing as a 400 after a full read.
        self.assertEqual(response.status_code, 413)

    def test_feedback_report_rejects_invalid_payload(self):
        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            client = self._client()
            response = client.post(
                "/api/feedback/report",
                json={"title": "No", "description": "short"},
            )

        self.assertEqual(response.status_code, 422)

    def test_feedback_report_returns_generic_failure_message(self):
        send_mock = AsyncMock(side_effect=RuntimeError("smtp trace"))

        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            client = self._client()
            with patch("app.api.routes.feedback.get_mail_sender", return_value=SimpleNamespace(send=send_mock)):
                response = client.post(
                    "/api/feedback/report",
                    json={
                        "title": "Profile layout shifted",
                        "description": "The profile header overlaps the first post after rotating the phone.",
                    },
                )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Couldn’t send your report right now."})

    def test_feedback_report_capture_mode_survives_unwritable_relative_mail_dir(self):
        original_cwd = os.getcwd()
        with TemporaryDirectory() as workspace_dir, TemporaryDirectory() as tmp_dir:
            os.chdir(workspace_dir)
            os.chmod(workspace_dir, stat.S_IREAD | stat.S_IEXEC)
            os.environ["TMPDIR"] = tmp_dir
            settings.MAIL_PROVIDER = "capture"
            settings.MAIL_CAPTURE_DIR = "tmp/mail"
            settings.FEEDBACK_REPORT_TO_EMAIL = "beta@example.com"
            try:
                with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
                    client = self._client()
                    response = client.post(
                        "/api/feedback/report",
                        json={
                            "title": "Capture fallback",
                            "description": "The report should still send when the relative capture directory is not writable.",
                        },
                    )
            finally:
                os.chdir(original_cwd)
                os.environ.pop("TMPDIR", None)
                os.chmod(workspace_dir, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

        self.assertEqual(response.status_code, 200)

    def test_feedback_report_rate_limits_after_repeated_submissions(self):
        client = self._client()

        with TemporaryDirectory() as temp_dir:
            settings.MAIL_PROVIDER = "capture"
            settings.MAIL_CAPTURE_DIR = temp_dir
            with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
                for _ in range(3):
                    response = client.post(
                        "/api/feedback/report",
                        json={
                            "title": "Something feels off",
                            "description": "This is a long enough beta feedback report to pass validation cleanly.",
                        },
                    )
                    self.assertEqual(response.status_code, 200)

                blocked = client.post(
                    "/api/feedback/report",
                    json={
                        "title": "Something feels off",
                        "description": "This is a long enough beta feedback report to pass validation cleanly.",
                    },
                )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"], "You're doing that too often. Please wait and try again.")
        self.assertEqual(blocked.headers["x-ratelimit-policy"], "feedback-report-user-burst")
