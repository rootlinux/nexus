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
from urllib.parse import urlparse

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api import deps
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.admin_audit_log import AdminAuditLog
from app.models.staff_permission import StaffPermission, StaffRole
from tests.media_test_support import create_test_user

SAMPLE_PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c/aAAAAAASUVORK5CYII=")


class FeedbackCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.attachment_dir = tempfile.mkdtemp(prefix="feedback-capability-attachments-")
        self._original_attachment_dir = settings.FEEDBACK_ATTACHMENT_LOCAL_DIR
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self.attachment_dir

        self.mail_dir = tempfile.mkdtemp(prefix="feedback-capability-mail-")
        self._original_mail_provider = settings.MAIL_PROVIDER
        self._original_mail_capture_dir = settings.MAIL_CAPTURE_DIR
        settings.MAIL_PROVIDER = "capture"
        settings.MAIL_CAPTURE_DIR = self.mail_dir

        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_sf = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_sf() as session:
                reporter = await create_test_user(session, username=f"reporter-{secrets.token_hex(4)}")
                await session.flush()
                self.reporter_id = reporter.id

                moderator = await create_test_user(session, username=f"moderator-{secrets.token_hex(4)}")
                await session.flush()
                session.add(StaffPermission(user_id=moderator.id, role=StaffRole.MODERATOR, can_view_feedback=False))
                self.moderator_id = moderator.id

                admin = await create_test_user(session, username=f"admin-{secrets.token_hex(4)}")
                await session.flush()
                session.add(StaffPermission(user_id=admin.id, role=StaffRole.ADMIN, can_view_feedback=True))
                self.admin_id = admin.id

                await session.commit()
        finally:
            await temp_engine.dispose()

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self._rate_limit_patch = patch("app.api.routes.feedback.enforce_rate_limits", new=AsyncMock())
        self._rate_limit_patch.start()

    async def asyncTearDown(self):
        self._rate_limit_patch.stop()
        app.dependency_overrides.clear()
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self._original_attachment_dir
        settings.MAIL_PROVIDER = self._original_mail_provider
        settings.MAIL_CAPTURE_DIR = self._original_mail_capture_dir
        shutil.rmtree(self.attachment_dir, ignore_errors=True)
        shutil.rmtree(self.mail_dir, ignore_errors=True)
        await self.engine.dispose()

    def _override_reporter(self):
        async def override_reporter():
            return SimpleNamespace(
                id=self.reporter_id, username="reporter", email="reporter@example.com",
                status=None, is_active=True,
            )
        app.dependency_overrides[deps.get_current_user] = override_reporter

    def _override_reader(self, user_id: int, *, role: StaffRole, can_view_feedback: bool):
        async def override_reader():
            return SimpleNamespace(
                id=user_id, username="reader", email="reader@example.com", status=None, is_active=True,
                staff_permission=SimpleNamespace(role=role, can_view_feedback=can_view_feedback),
            )
        app.dependency_overrides[deps.get_current_user] = override_reader

    async def _submit_report_with_attachment(self, client: httpx.AsyncClient) -> str:
        self._override_reporter()
        response = await client.post(
            "/api/feedback/report",
            data={
                "title": "Capability scoping check",
                "description": "Verifying feedback attachment downloads are scoped to the right capability.",
            },
            files={"attachment": ("shot.png", SAMPLE_PNG, "image/png")},
        )
        assert response.status_code == 200, response.text
        captured_files = sorted(glob.glob(f"{self.mail_dir}/*.json"))
        payload = json.loads(open(captured_files[-1], encoding="utf-8").read())
        for line in payload["text_body"].splitlines():
            if line.startswith("Attachment URL: "):
                return line.split("Attachment URL: ", 1)[1]
        raise AssertionError("no attachment URL captured in the outgoing message")

    async def _audit_rows_for_storage_key(self, storage_key: str) -> list[AdminAuditLog]:
        db = self.session_factory()
        try:
            rows = (await db.scalars(
                select(AdminAuditLog).where(AdminAuditLog.target_id == storage_key).order_by(AdminAuditLog.id.asc())
            )).all()
            return list(rows)
        finally:
            await db.close()

    @staticmethod
    def _storage_key_from_url(attachment_url: str) -> str:
        return urlparse(attachment_url).path.rsplit("/", 1)[-1]

    async def test_moderator_without_capability_gets_403_and_exactly_one_denied_audit_row(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_report_with_attachment(client)
            self._override_reader(self.moderator_id, role=StaffRole.MODERATOR, can_view_feedback=False)
            response = await client.get(attachment_url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Insufficient permissions for this action"})

        storage_key = self._storage_key_from_url(attachment_url)
        rows = await self._audit_rows_for_storage_key(storage_key)
        denied_rows = [r for r in rows if r.action == "feedback.attachment_access_denied"]
        self.assertEqual(len(denied_rows), 1)
        self.assertFalse(denied_rows[0].success)
        self.assertEqual(denied_rows[0].after_json.get("storage_key"), storage_key)
        self.assertIn("feedback_report_id", denied_rows[0].after_json)
        # Exactly one row total from this request — no duplicate/zero rows.
        self.assertEqual(len(rows), 1)

    async def test_admin_with_capability_gets_200_and_downloaded_audit_row(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_report_with_attachment(client)
            self._override_reader(self.admin_id, role=StaffRole.ADMIN, can_view_feedback=True)
            response = await client.get(attachment_url)

        self.assertEqual(response.status_code, 200)
        storage_key = self._storage_key_from_url(attachment_url)
        rows = await self._audit_rows_for_storage_key(storage_key)
        downloaded_rows = [r for r in rows if r.action == "feedback.attachment_downloaded"]
        self.assertEqual(len(downloaded_rows), 1)
        self.assertTrue(downloaded_rows[0].success)
        self.assertEqual(downloaded_rows[0].after_json.get("verification_path"), "new")

    async def test_unauthenticated_request_gets_401_and_produces_no_audit_row(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_report_with_attachment(client)
            app.dependency_overrides.pop(deps.get_current_user, None)
            response = await client.get(attachment_url)

        self.assertEqual(response.status_code, 401)
        storage_key = self._storage_key_from_url(attachment_url)
        rows = await self._audit_rows_for_storage_key(storage_key)
        # Documented, intentional gap: bare-unauthenticated rejections happen
        # inside the shared get_current_user dependency, before
        # require_feedback_read_with_audit's own body ever runs — this locks
        # in that documented behavior rather than silently passing either way.
        self.assertEqual(rows, [])

    async def test_route_dependency_is_require_feedback_read_with_audit_not_a_manual_check(self):
        import inspect

        from app.api.routes.feedback import download_feedback_attachment, require_feedback_read_with_audit

        sig = inspect.signature(download_feedback_attachment)
        current_user_param = sig.parameters["current_user"]
        self.assertIs(current_user_param.default.dependency, require_feedback_read_with_audit)

    async def test_denial_audit_write_failure_still_results_in_403_never_accidental_grant(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_report_with_attachment(client)
            self._override_reader(self.moderator_id, role=StaffRole.MODERATOR, can_view_feedback=False)
            with patch("app.api.routes.feedback.write_audit_log", new=AsyncMock(side_effect=RuntimeError("db down"))):
                response = await client.get(attachment_url)

        self.assertEqual(response.status_code, 403)

    async def test_no_audit_payload_ever_contains_sig_url_or_credential_material(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            attachment_url = await self._submit_report_with_attachment(client)
            self._override_reader(self.moderator_id, role=StaffRole.MODERATOR, can_view_feedback=False)
            await client.get(attachment_url)

        storage_key = self._storage_key_from_url(attachment_url)
        rows = await self._audit_rows_for_storage_key(storage_key)
        self.assertTrue(rows)
        for row in rows:
            serialized = json.dumps(row.after_json or {})
            self.assertNotIn("sig=", serialized)
            self.assertNotIn(attachment_url, serialized)
            self.assertNotIn(settings.SECRET_KEY, serialized)


if __name__ == "__main__":
    unittest.main()
