import glob
import inspect
import json
import os
import secrets
import shutil
import tempfile
import unittest
from base64 import b64decode
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api import deps
from app.api.routes.feedback import (
    FeedbackAttachmentAccessDenied,
    _feedback_attachment_signature,
    _is_safe_storage_key,
    _legacy_feedback_attachment_signature,
    _verify_feedback_attachment_access,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.signing_keys import derive_purpose_key, SigningPurpose
from app.main import app
from app.models.admin_audit_log import AdminAuditLog
from app.models.media_asset import MediaAsset
from app.models.staff_permission import StaffPermission, StaffRole
from tests.media_test_support import create_test_user

SAMPLE_PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c/aAAAAAASUVORK5CYII=")


def _make_url(*, storage_key: str, feedback_report_id: int | None, expires: int, sig: str) -> str:
    params: dict = {"expires": expires, "sig": sig}
    if feedback_report_id is not None:
        params["feedback_report_id"] = feedback_report_id
    return f"/api/feedback/attachments/{storage_key}?{urlencode(params)}"


class FeedbackAttachmentBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.attachment_dir = tempfile.mkdtemp(prefix="feedback-binding-attachments-")
        self._original_attachment_dir = settings.FEEDBACK_ATTACHMENT_LOCAL_DIR
        settings.FEEDBACK_ATTACHMENT_LOCAL_DIR = self.attachment_dir

        self.mail_dir = tempfile.mkdtemp(prefix="feedback-binding-mail-")
        self._original_mail_provider = settings.MAIL_PROVIDER
        self._original_mail_capture_dir = settings.MAIL_CAPTURE_DIR
        settings.MAIL_PROVIDER = "capture"
        settings.MAIL_CAPTURE_DIR = self.mail_dir

        self._original_legacy_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL

        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_sf = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_sf() as session:
                reporter = await create_test_user(session, username=f"reporter-{secrets.token_hex(4)}")
                await session.flush()
                self.reporter_id = reporter.id

                admin = await create_test_user(session, username=f"admin-{secrets.token_hex(4)}")
                await session.flush()
                session.add(StaffPermission(user_id=admin.id, role=StaffRole.ADMIN, can_view_feedback=True))
                self.admin_id = admin.id

                moderator = await create_test_user(session, username=f"moderator-{secrets.token_hex(4)}")
                await session.flush()
                session.add(StaffPermission(user_id=moderator.id, role=StaffRole.MODERATOR, can_view_feedback=False))
                self.moderator_id = moderator.id

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
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = self._original_legacy_deadline
        shutil.rmtree(self.attachment_dir, ignore_errors=True)
        shutil.rmtree(self.mail_dir, ignore_errors=True)
        await self.engine.dispose()

    def _override_reporter(self):
        async def override():
            return SimpleNamespace(
                id=self.reporter_id, username="reporter", email="reporter@example.com",
                status=None, is_active=True,
            )
        app.dependency_overrides[deps.get_current_user] = override

    def _override_admin_reader(self):
        async def override():
            return SimpleNamespace(
                id=self.admin_id, username="admin", email="admin@example.com", status=None, is_active=True,
                staff_permission=SimpleNamespace(role=StaffRole.ADMIN, can_view_feedback=True),
            )
        app.dependency_overrides[deps.get_current_user] = override

    def _override_moderator_reader(self):
        async def override():
            return SimpleNamespace(
                id=self.moderator_id, username="moderator", email="moderator@example.com", status=None, is_active=True,
                staff_permission=SimpleNamespace(role=StaffRole.MODERATOR, can_view_feedback=False),
            )
        app.dependency_overrides[deps.get_current_user] = override

    async def _submit_report_with_attachment(self, client: httpx.AsyncClient) -> tuple[str, int]:
        """Returns (storage_key, feedback_report_id) read back from the real
        MediaAsset row, not parsed from the emailed link text — this test
        file constructs its own signed URLs directly instead."""
        self._override_reporter()
        response = await client.post(
            "/api/feedback/report",
            data={
                "title": "Attachment binding check",
                "description": "Verifying feedback attachment links are bound to their report and file.",
            },
            files={"attachment": ("shot.png", SAMPLE_PNG, "image/png")},
        )
        assert response.status_code == 200, response.text

        db = self.session_factory()
        try:
            asset = (await db.scalars(
                select(MediaAsset)
                .where(MediaAsset.owner_user_id == self.reporter_id, MediaAsset.attached_to_type == "feedback_report")
                .order_by(MediaAsset.id.desc())
            )).first()
            return asset.storage_key, asset.attached_to_id
        finally:
            await db.close()

    async def _audit_rows(self, storage_key: str) -> list[AdminAuditLog]:
        db = self.session_factory()
        try:
            rows = (await db.scalars(
                select(AdminAuditLog).where(AdminAuditLog.target_id == storage_key).order_by(AdminAuditLog.id.asc())
            )).all()
            return list(rows)
        finally:
            await db.close()

    @staticmethod
    def _fresh_expires(*, past: bool = False) -> int:
        return int(datetime.now(timezone.utc).timestamp()) + (-3600 if past else 3600)

    async def test_wrong_feedback_report_id_with_internally_valid_signature_gets_binding_mismatch(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, real_fid = await self._submit_report_with_attachment(client)
            wrong_fid = real_fid + 999_000
            expires = self._fresh_expires()
            sig = _feedback_attachment_signature(feedback_report_id=wrong_fid, storage_key=storage_key, expires=expires)
            url = _make_url(storage_key=storage_key, feedback_report_id=wrong_fid, expires=expires, sig=sig)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Invalid or expired attachment link."})
        rows = await self._audit_rows(storage_key)
        failed = [r for r in rows if r.action == "feedback.attachment_verification_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].after_json.get("reason"), "binding_mismatch")

    async def test_tampered_signature_gets_invalid_signature_reason(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, real_fid = await self._submit_report_with_attachment(client)
            expires = self._fresh_expires()
            sig = _feedback_attachment_signature(feedback_report_id=real_fid, storage_key=storage_key, expires=expires)
            tampered_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
            url = _make_url(storage_key=storage_key, feedback_report_id=real_fid, expires=expires, sig=tampered_sig)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 403)
        rows = await self._audit_rows(storage_key)
        failed = [r for r in rows if r.action == "feedback.attachment_verification_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].after_json.get("reason"), "invalid_signature")

    async def test_expired_link_gets_expired_reason(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, real_fid = await self._submit_report_with_attachment(client)
            expires = self._fresh_expires(past=True)
            sig = _feedback_attachment_signature(feedback_report_id=real_fid, storage_key=storage_key, expires=expires)
            url = _make_url(storage_key=storage_key, feedback_report_id=real_fid, expires=expires, sig=sig)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 403)
        rows = await self._audit_rows(storage_key)
        failed = [r for r in rows if r.action == "feedback.attachment_verification_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].after_json.get("reason"), "expired")

    async def test_replaying_link_against_a_different_report_id_without_resigning_fails_signature(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key_a, fid_a = await self._submit_report_with_attachment(client)
            _storage_key_b, fid_b = await self._submit_report_with_attachment(client)
            self.assertNotEqual(fid_a, fid_b)

            expires = self._fresh_expires()
            sig_for_a = _feedback_attachment_signature(feedback_report_id=fid_a, storage_key=storage_key_a, expires=expires)
            # Swap in report B's id but keep report A's signature — the
            # signature covers both fields, so this must fail, not silently
            # bind to report B.
            url = _make_url(storage_key=storage_key_a, feedback_report_id=fid_b, expires=expires, sig=sig_for_a)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 403)
        rows = await self._audit_rows(storage_key_a)
        failed = [r for r in rows if r.action == "feedback.attachment_verification_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].after_json.get("reason"), "invalid_signature")

    async def test_genuine_legacy_link_verifies_while_window_open_and_reports_legacy_path(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, _real_fid = await self._submit_report_with_attachment(client)
            expires = self._fresh_expires()
            legacy_sig = _legacy_feedback_attachment_signature(storage_key, expires)
            url = _make_url(storage_key=storage_key, feedback_report_id=None, expires=expires, sig=legacy_sig)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 200)
        rows = await self._audit_rows(storage_key)
        downloaded = [r for r in rows if r.action == "feedback.attachment_downloaded"]
        self.assertEqual(len(downloaded), 1)
        self.assertEqual(downloaded[0].after_json.get("verification_path"), "legacy")

    async def test_mocked_audit_write_failure_during_verification_failure_still_403(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, real_fid = await self._submit_report_with_attachment(client)
            expires = self._fresh_expires()
            sig = _feedback_attachment_signature(feedback_report_id=real_fid, storage_key=storage_key, expires=expires)
            tampered_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
            url = _make_url(storage_key=storage_key, feedback_report_id=real_fid, expires=expires, sig=tampered_sig)

            self._override_admin_reader()
            with patch("app.api.routes.feedback.write_audit_log", new=AsyncMock(side_effect=RuntimeError("db down"))):
                response = await client.get(url)

        self.assertEqual(response.status_code, 403)

    async def test_absent_feedback_report_id_rejected_once_legacy_window_is_closed(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None  # the default — legacy fully disabled
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, _real_fid = await self._submit_report_with_attachment(client)
            expires = self._fresh_expires()
            # This would only verify if legacy fallback were allowed — with
            # it closed, absence of feedback_report_id must be rejected
            # outright, never silently treated as "must be legacy."
            legacy_sig = _legacy_feedback_attachment_signature(storage_key, expires)
            url = _make_url(storage_key=storage_key, feedback_report_id=None, expires=expires, sig=legacy_sig)

            self._override_admin_reader()
            response = await client.get(url)

        self.assertEqual(response.status_code, 403)
        rows = await self._audit_rows(storage_key)
        downloaded = [r for r in rows if r.action == "feedback.attachment_downloaded"]
        self.assertEqual(downloaded, [])  # verification_path never reached "legacy"
        failed = [r for r in rows if r.action == "feedback.attachment_verification_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].after_json.get("reason"), "invalid_signature")

    async def test_is_safe_storage_key_rejects_path_traversal_and_malformed_keys(self):
        for malicious_key in (
            "../../etc/passwd",
            "/etc/passwd",
            "not-a-uuid.png",
            "..%2F..%2Fetc%2Fpasswd.png",
        ):
            self.assertFalse(_is_safe_storage_key(malicious_key), f"expected {malicious_key!r} to be rejected")

    async def test_legacy_link_with_manipulated_storage_key_rejected_end_to_end(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        db = self.session_factory()
        try:
            malicious_key = "not-a-real-uuid.png"
            expires = self._fresh_expires()
            legacy_sig = _legacy_feedback_attachment_signature(malicious_key, expires)
            with self.assertRaises(FeedbackAttachmentAccessDenied) as ctx:
                await _verify_feedback_attachment_access(
                    db, storage_key=malicious_key, feedback_report_id=None, expires=expires, sig=legacy_sig,
                )
            self.assertEqual(ctx.exception.reason, "invalid_signature")
        finally:
            await db.close()

    async def test_verify_feedback_attachment_access_is_a_real_awaited_coroutine(self):
        self.assertTrue(inspect.iscoroutinefunction(_verify_feedback_attachment_access))

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            storage_key, real_fid = await self._submit_report_with_attachment(client)

        db = self.session_factory()
        try:
            expires = self._fresh_expires()
            sig = _feedback_attachment_signature(feedback_report_id=real_fid, storage_key=storage_key, expires=expires)
            scalar_calls = []
            real_scalar = db.scalar

            async def spy_scalar(statement):
                scalar_calls.append(statement)
                return await real_scalar(statement)

            db.scalar = spy_scalar
            result = await _verify_feedback_attachment_access(
                db, storage_key=storage_key, feedback_report_id=real_fid, expires=expires, sig=sig,
            )
            self.assertEqual(result.verification_path, "new")
            # Proves the MediaAsset lookup was a real, awaited DB query — not
            # fired-and-forgotten or skipped entirely.
            self.assertEqual(len(scalar_calls), 1)
        finally:
            await db.close()

    async def test_no_leak_of_sig_url_or_key_material_and_exactly_one_audit_row_per_attempt(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        derived_key_hex = derive_purpose_key(SigningPurpose.FEEDBACK_ATTACHMENT_LINK).hex()

        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            # Successful download.
            storage_key_ok, fid_ok = await self._submit_report_with_attachment(client)
            expires_ok = self._fresh_expires()
            sig_ok = _feedback_attachment_signature(feedback_report_id=fid_ok, storage_key=storage_key_ok, expires=expires_ok)
            self._override_admin_reader()
            ok_response = await client.get(_make_url(storage_key=storage_key_ok, feedback_report_id=fid_ok, expires=expires_ok, sig=sig_ok))
            self.assertEqual(ok_response.status_code, 200)

            # Capability-denied.
            storage_key_denied, fid_denied = await self._submit_report_with_attachment(client)
            expires_denied = self._fresh_expires()
            sig_denied = _feedback_attachment_signature(feedback_report_id=fid_denied, storage_key=storage_key_denied, expires=expires_denied)
            self._override_moderator_reader()
            denied_response = await client.get(_make_url(storage_key=storage_key_denied, feedback_report_id=fid_denied, expires=expires_denied, sig=sig_denied))
            self.assertEqual(denied_response.status_code, 403)

            # Verification-failed.
            storage_key_bad, fid_bad = await self._submit_report_with_attachment(client)
            expires_bad = self._fresh_expires()
            bad_sig = "0" * 64
            self._override_admin_reader()
            bad_response = await client.get(_make_url(storage_key=storage_key_bad, feedback_report_id=fid_bad, expires=expires_bad, sig=bad_sig))
            self.assertEqual(bad_response.status_code, 403)

        for storage_key, expected_count in (
            (storage_key_ok, 1), (storage_key_denied, 1), (storage_key_bad, 1),
        ):
            rows = await self._audit_rows(storage_key)
            self.assertEqual(len(rows), expected_count, f"unexpected audit row count for {storage_key}")
            for row in rows:
                serialized = json.dumps(row.after_json or {})
                self.assertNotIn("sig=", serialized)
                self.assertNotIn(sig_ok, serialized)
                self.assertNotIn(settings.SECRET_KEY, serialized)
                self.assertNotIn(derived_key_hex, serialized)


if __name__ == "__main__":
    unittest.main()
