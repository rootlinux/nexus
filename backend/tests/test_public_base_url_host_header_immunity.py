import glob
import json
import os
import secrets
import shutil
import tempfile
import unittest
from base64 import b64decode
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api import deps
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from tests.media_test_support import create_test_user

SAMPLE_PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c/aAAAAAASUVORK5CYII=")


class PublicBaseUrlHostHeaderImmunityTests(unittest.IsolatedAsyncioTestCase):
    """The specifically-required Task 7 test: attachment-link generation
    must never depend on the incoming request's Host / X-Forwarded-Host
    headers, both of which are attacker-influenceable. Verified via the
    only observable surface — the URL actually emailed out — since
    access_url is never returned in the HTTP response itself."""

    async def asyncSetUp(self):
        self.attachment_dir = tempfile.mkdtemp(prefix="host-immunity-attachments-")
        self._original_attachment_dir = settings.FEEDBACK_ATTACHMENT_LOCAL_DIR
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self.attachment_dir

        self.mail_dir = tempfile.mkdtemp(prefix="host-immunity-mail-")
        self._original_mail_provider = settings.MAIL_PROVIDER
        self._original_mail_capture_dir = settings.MAIL_CAPTURE_DIR
        settings.MAIL_PROVIDER = "capture"
        settings.MAIL_CAPTURE_DIR = self.mail_dir

        self._original_trust_proxy_headers = settings.TRUST_PROXY_HEADERS

        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_sf = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_sf() as session:
                reporter = await create_test_user(session, username=f"reporter-{secrets.token_hex(4)}")
                await session.flush()
                self.reporter_id = reporter.id
                await session.commit()
        finally:
            await temp_engine.dispose()

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db

        async def override_reporter():
            return SimpleNamespace(
                id=self.reporter_id, username="reporter", email="reporter@example.com",
                status=None, is_active=True,
            )

        app.dependency_overrides[deps.get_current_user] = override_reporter
        self._rate_limit_patch = patch("app.api.routes.feedback.enforce_rate_limits", new=AsyncMock())
        self._rate_limit_patch.start()

    async def asyncTearDown(self):
        self._rate_limit_patch.stop()
        app.dependency_overrides.clear()
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self._original_attachment_dir
        settings.MAIL_PROVIDER = self._original_mail_provider
        settings.MAIL_CAPTURE_DIR = self._original_mail_capture_dir
        settings.TRUST_PROXY_HEADERS = self._original_trust_proxy_headers
        shutil.rmtree(self.attachment_dir, ignore_errors=True)
        shutil.rmtree(self.mail_dir, ignore_errors=True)
        await self.engine.dispose()

    async def _submit_and_capture_attachment_url(self, client: httpx.AsyncClient, *, headers: dict) -> str:
        response = await client.post(
            "/api/feedback/report",
            data={
                "title": "Host header immunity check",
                "description": "Confirming the generated attachment URL ignores forged host headers entirely.",
            },
            files={"attachment": ("shot.png", SAMPLE_PNG, "image/png")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        captured_files = sorted(glob.glob(f"{self.mail_dir}/*.json"))
        payload = json.loads(open(captured_files[-1], encoding="utf-8").read())
        for line in payload["text_body"].splitlines():
            if line.startswith("Attachment URL: "):
                return line.split("Attachment URL: ", 1)[1]
        raise AssertionError("no attachment URL captured in the outgoing message")

    async def _assert_url_immune(self, *, headers: dict, trust_proxy_headers: bool, forbidden_substring: str):
        settings.TRUST_PROXY_HEADERS = trust_proxy_headers
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_and_capture_attachment_url(client, headers=headers)

        self.assertTrue(
            attachment_url.startswith(settings.API_PUBLIC_BASE_URL),
            f"expected {attachment_url!r} to start with {settings.API_PUBLIC_BASE_URL!r}",
        )
        self.assertNotIn(forbidden_substring, attachment_url)

    async def test_forged_x_forwarded_host_header_ignored_with_proxy_trust_disabled(self):
        # X-Forwarded-Host is not covered by HostValidationMiddleware (it
        # only checks the real Host header), so this genuinely reaches the
        # route unblocked — the real proxy-misconfiguration scenario.
        await self._assert_url_immune(
            headers={"x-forwarded-host": "evil.example.com"}, trust_proxy_headers=False,
            forbidden_substring="evil.example.com",
        )

    async def test_forged_x_forwarded_host_header_ignored_with_proxy_trust_enabled(self):
        # Enabling TrustedProxyHeadersMiddleware would normally make
        # request.base_url follow X-Forwarded-Host for a trusted proxy —
        # this must make no difference here, since the URL-building code
        # never reads request.base_url in the first place, regardless of
        # this setting.
        await self._assert_url_immune(
            headers={"x-forwarded-host": "evil.example.com"}, trust_proxy_headers=True,
            forbidden_substring="evil.example.com",
        )

    async def test_allowed_but_different_host_header_still_ignored(self):
        # HostValidationMiddleware legitimately rejects an outright forged
        # Host header (e.g. evil.example.com) before the route ever runs —
        # that's a separate, correctly-functioning defense-in-depth layer,
        # not what this test is about. To isolate whether OUR code reads
        # request.base_url at all, use a Host value that IS on the allowlist
        # (so the request reaches the route) but differs from
        # API_PUBLIC_BASE_URL's own host — the generated URL must still
        # follow the configured value, never the request's Host header.
        self.assertIn("127.0.0.1", settings.ALLOWED_HOSTS)
        self.assertNotIn("127.0.0.1", settings.API_PUBLIC_BASE_URL)
        await self._assert_url_immune(
            headers={"host": "127.0.0.1"}, trust_proxy_headers=False, forbidden_substring="://127.0.0.1",
        )


if __name__ == "__main__":
    unittest.main()
