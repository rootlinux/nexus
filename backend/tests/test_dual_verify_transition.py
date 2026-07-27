import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import hmac as hmac_module
import jwt
from hashlib import sha256
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from pydantic import ValidationError

from app.api.deps import _decode_access_token
from app.api.routes.feedback import (
    FeedbackAttachmentAccessDenied,
    _feedback_attachment_signature,
    _verify_feedback_attachment_access,
)
from app.core.config import Settings, settings
from app.core.signing_keys import SigningPurpose, decode_jwt_with_fallback, derive_purpose_key
from app.models.email_change_token import EmailChangeToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.password_reset_token import PasswordResetToken
from app.services.account_security import (
    get_email_change_token_by_secret,
    get_email_verification_token_by_secret,
    get_password_reset_token_by_secret,
    hash_account_secret,
)
from tests.media_test_support import create_test_user


def _legacy_hash(secret: str) -> str:
    return hmac_module.new(settings.SECRET_KEY.encode("utf-8"), secret.encode("utf-8"), "sha256").hexdigest()


def _legacy_jwt(*, sub: str = "1", purpose: str | None = None) -> str:
    payload: dict = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    if purpose is not None:
        payload["purpose"] = purpose
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


class DualVerifyTransitionJwtTests(unittest.TestCase):
    """Covers the 3 JWT-based purposes: access, MFA session, admin recovery."""

    def setUp(self):
        self._original_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL

    def tearDown(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = self._original_deadline

    def test_legacy_jwt_rejected_by_default_for_all_three_purposes(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        for purpose in (SigningPurpose.JWT_ACCESS, SigningPurpose.MFA_SESSION, SigningPurpose.ADMIN_WEBAUTHN_RECOVERY):
            token = _legacy_jwt(purpose=purpose.value)
            with self.assertRaises(jwt.InvalidSignatureError):
                decode_jwt_with_fallback(token, purpose)

    def test_legacy_jwt_verifies_with_future_deadline_configured(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        for purpose in (SigningPurpose.JWT_ACCESS, SigningPurpose.MFA_SESSION, SigningPurpose.ADMIN_WEBAUTHN_RECOVERY):
            token = _legacy_jwt(purpose=purpose.value)
            payload, verification_path = decode_jwt_with_fallback(token, purpose)
            self.assertEqual(verification_path, "legacy")
            self.assertEqual(payload["sub"], "1")

    def test_legacy_jwt_rejected_again_once_deadline_passes(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) - timedelta(minutes=1)
        token = _legacy_jwt(purpose=SigningPurpose.JWT_ACCESS.value)
        with self.assertRaises(jwt.InvalidSignatureError):
            decode_jwt_with_fallback(token, SigningPurpose.JWT_ACCESS)

    def test_past_deadline_behaves_identically_to_none(self):
        token = _legacy_jwt(purpose=SigningPurpose.JWT_ACCESS.value)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        with self.assertRaises(jwt.InvalidSignatureError):
            decode_jwt_with_fallback(token, SigningPurpose.JWT_ACCESS)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) - timedelta(days=1)
        with self.assertRaises(jwt.InvalidSignatureError):
            decode_jwt_with_fallback(token, SigningPurpose.JWT_ACCESS)

    def test_newly_issued_access_token_always_uses_new_scheme_regardless_of_setting(self):
        for deadline in (None, datetime.now(timezone.utc) + timedelta(minutes=5)):
            settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = deadline
            from app.core.security import create_access_token

            token = create_access_token({"sub": "42"})
            payload, verification_path = decode_jwt_with_fallback(token, SigningPurpose.JWT_ACCESS)
            self.assertEqual(verification_path, "new")
            self.assertEqual(payload["purpose"], SigningPurpose.JWT_ACCESS.value)

    def test_decode_access_token_end_to_end_with_legacy_access_jwt(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        token = _legacy_jwt(purpose=None)  # grandfathered: old access tokens carried no purpose claim
        token_data = _decode_access_token(token)
        self.assertEqual(token_data.user_id, 1)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        with self.assertRaises(HTTPException) as ctx:
            _decode_access_token(token)
        self.assertEqual(ctx.exception.status_code, 401)


class DualVerifyTransitionAccountSecretTests(unittest.IsolatedAsyncioTestCase):
    """Covers the 3 HMAC-based account-secret purposes: password reset,
    email verification, email change."""

    async def asyncSetUp(self):
        self._original_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.session_factory()
        self.user = await create_test_user(self.db)
        await self.db.commit()

    async def asyncTearDown(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = self._original_deadline
        await self.db.close()
        await self.engine.dispose()

    async def _seed_legacy_row(self, model, *, extra_field: dict, secret: str):
        row = model(
            user_id=self.user.id,
            token_hash=_legacy_hash(secret),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            **extra_field,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def test_legacy_password_reset_token_rejected_by_default_verifies_with_future_deadline(self):
        secret = "legacy-reset-secret-0123456789"
        await self._seed_legacy_row(PasswordResetToken, extra_field={"email": self.user.email}, secret=secret)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        self.assertIsNone(await get_password_reset_token_by_secret(self.db, secret))

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        found = await get_password_reset_token_by_secret(self.db, secret)
        self.assertIsNotNone(found)

    async def test_legacy_email_verification_token_rejected_by_default_verifies_with_future_deadline(self):
        secret = "legacy-verify-secret-0123456789"
        await self._seed_legacy_row(EmailVerificationToken, extra_field={"email": self.user.email}, secret=secret)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        self.assertIsNone(await get_email_verification_token_by_secret(self.db, secret))

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        found = await get_email_verification_token_by_secret(self.db, secret)
        self.assertIsNotNone(found)

    async def test_legacy_email_change_token_rejected_by_default_verifies_with_future_deadline(self):
        secret = "legacy-change-secret-0123456789"
        await self._seed_legacy_row(EmailChangeToken, extra_field={"pending_email": "new@example.com"}, secret=secret)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        self.assertIsNone(await get_email_change_token_by_secret(self.db, secret))

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        found = await get_email_change_token_by_secret(self.db, secret)
        self.assertIsNotNone(found)

    async def test_past_deadline_behaves_identically_to_none_for_account_secrets(self):
        secret = "legacy-reset-secret-past-0123456789"
        await self._seed_legacy_row(PasswordResetToken, extra_field={"email": self.user.email}, secret=secret)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        self.assertIsNone(await get_password_reset_token_by_secret(self.db, secret))

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertIsNone(await get_password_reset_token_by_secret(self.db, secret))

    async def test_newly_issued_secret_always_uses_new_scheme_regardless_of_setting(self):
        for deadline in (None, datetime.now(timezone.utc) + timedelta(minutes=5)):
            settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = deadline
            new_hash = hash_account_secret("some-fresh-secret", purpose=SigningPurpose.PASSWORD_RESET)
            self.assertNotEqual(new_hash, _legacy_hash("some-fresh-secret"))


class DualVerifyTransitionFeedbackAttachmentTests(unittest.IsolatedAsyncioTestCase):
    """Round 2 Task 7 rewrote _verify_feedback_attachment_access into a
    genuinely async, DB-backed function (db, storage_key, feedback_report_id,
    expires, sig) returning a typed FeedbackAttachmentVerification / raising
    FeedbackAttachmentAccessDenied, and _feedback_attachment_signature now
    requires feedback_report_id too. These tests exercise Task 7's LEGACY
    branch (feedback_report_id=None) specifically, since that's the exact
    scheme this dual-verify-gating test class cares about — the new-format
    branch's own binding/signature behavior is covered exhaustively in
    test_feedback_attachment_binding.py."""

    async def asyncSetUp(self):
        self._original_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.session_factory()

    async def asyncTearDown(self):
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = self._original_deadline
        await self.db.close()
        await self.engine.dispose()

    def _legacy_signature(self, storage_key: str, expires_at: int) -> str:
        payload = f"{storage_key}:{expires_at}".encode("utf-8")
        return hmac_module.new(settings.SECRET_KEY.encode("utf-8"), payload, sha256).hexdigest()

    async def test_legacy_feedback_link_rejected_by_default_verifies_with_future_deadline(self):
        storage_key = "11111111-1111-1111-1111-111111111111.png"
        expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600
        legacy_sig = self._legacy_signature(storage_key, expires_at)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = None
        with self.assertRaises(FeedbackAttachmentAccessDenied):
            await _verify_feedback_attachment_access(
                self.db, storage_key=storage_key, feedback_report_id=None, expires=expires_at, sig=legacy_sig,
            )

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        result = await _verify_feedback_attachment_access(
            self.db, storage_key=storage_key, feedback_report_id=None, expires=expires_at, sig=legacy_sig,
        )
        self.assertEqual(result.verification_path, "legacy")

    async def test_past_deadline_behaves_identically_to_none_for_feedback_link(self):
        storage_key = "22222222-2222-2222-2222-222222222222.png"
        expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600
        legacy_sig = self._legacy_signature(storage_key, expires_at)

        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) - timedelta(days=1)
        with self.assertRaises(FeedbackAttachmentAccessDenied):
            await _verify_feedback_attachment_access(
                self.db, storage_key=storage_key, feedback_report_id=None, expires=expires_at, sig=legacy_sig,
            )

    async def test_newly_generated_link_always_uses_new_scheme_regardless_of_setting(self):
        storage_key = "33333333-3333-3333-3333-333333333333.png"
        expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600
        for deadline in (None, datetime.now(timezone.utc) + timedelta(minutes=5)):
            settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = deadline
            new_sig = _feedback_attachment_signature(
                feedback_report_id=1, storage_key=storage_key, expires=expires_at,
            )
            self.assertNotEqual(new_sig, self._legacy_signature(storage_key, expires_at))


class SigningKeyLegacyVerifyUntilBootValidationTests(unittest.TestCase):
    """Boot-time validation and the startup-warning log line — constructing
    a FRESH Settings() instance, since mutating the module-level `settings`
    singleton's attribute directly never re-runs its model validators."""

    def _base_env(self) -> dict:
        return {
            "DATABASE_URL": settings.DATABASE_URL,
            "REDIS_URL": settings.REDIS_URL,
            "SECRET_KEY": settings.SECRET_KEY,
        }

    def test_naive_datetime_is_rejected_at_boot(self):
        with self.assertRaises(ValidationError):
            Settings(**self._base_env(), SIGNING_KEY_LEGACY_VERIFY_UNTIL="2026-08-15T00:00:00")

    def test_timezone_aware_future_datetime_is_accepted(self):
        fresh = Settings(**self._base_env(), SIGNING_KEY_LEGACY_VERIFY_UNTIL="2099-08-15T00:00:00+00:00")
        self.assertIsNotNone(fresh.SIGNING_KEY_LEGACY_VERIFY_UNTIL)

    def test_warning_logged_only_when_future_deadline_configured(self):
        with self.assertLogs("app.core.config", level="WARNING") as log_ctx:
            Settings(**self._base_env(), SIGNING_KEY_LEGACY_VERIFY_UNTIL="2099-08-15T00:00:00+00:00")
        self.assertTrue(any("Legacy signing-key fallback is active" in msg for msg in log_ctx.output))

    def test_no_warning_when_unset(self):
        with self.assertRaises(AssertionError):
            # assertNoLogs isn't available on all Python versions used here —
            # emulate it: assertLogs raises AssertionError if nothing was logged.
            with self.assertLogs("app.core.config", level="WARNING"):
                Settings(**self._base_env(), SIGNING_KEY_LEGACY_VERIFY_UNTIL=None)

    def test_no_warning_when_deadline_already_passed(self):
        with self.assertRaises(AssertionError):
            with self.assertLogs("app.core.config", level="WARNING"):
                Settings(**self._base_env(), SIGNING_KEY_LEGACY_VERIFY_UNTIL="2020-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
