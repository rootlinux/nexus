import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import jwt
from fastapi import HTTPException

from app.api.deps import _decode_access_token
from app.core.config import settings
from app.core.signing_keys import SigningPurpose, derive_purpose_key


def _make_jwt(key: bytes | str, *, purpose: str | None, sub: str = "1") -> str:
    payload: dict = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    if purpose is not None:
        payload["purpose"] = purpose
    return jwt.encode(payload, key, algorithm=settings.ALGORITHM)


class SigningKeyPurposeSeparationTests(unittest.TestCase):
    def test_derive_purpose_key_produces_distinct_keys_across_all_purposes(self):
        keys = {purpose: derive_purpose_key(purpose) for purpose in SigningPurpose}
        self.assertEqual(len(set(keys.values())), len(SigningPurpose))

    def test_derive_purpose_key_is_deterministic_for_the_same_purpose(self):
        self.assertEqual(
            derive_purpose_key(SigningPurpose.JWT_ACCESS),
            derive_purpose_key(SigningPurpose.JWT_ACCESS),
        )

    def test_token_signed_for_one_purpose_fails_verification_against_another(self):
        token = _make_jwt(derive_purpose_key(SigningPurpose.MFA_SESSION), purpose=SigningPurpose.MFA_SESSION.value)
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, derive_purpose_key(SigningPurpose.ADMIN_WEBAUTHN_RECOVERY), algorithms=[settings.ALGORITHM])

    def test_decode_access_token_rejects_mfa_session_jwt_presented_as_bearer_new_key_path(self):
        mfa_token = _make_jwt(derive_purpose_key(SigningPurpose.MFA_SESSION), purpose=SigningPurpose.MFA_SESSION.value)
        with self.assertRaises(HTTPException) as ctx:
            _decode_access_token(mfa_token)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_decode_access_token_rejects_admin_recovery_jwt_presented_as_bearer_new_key_path(self):
        recovery_token = _make_jwt(
            derive_purpose_key(SigningPurpose.ADMIN_WEBAUTHN_RECOVERY),
            purpose=SigningPurpose.ADMIN_WEBAUTHN_RECOVERY.value,
        )
        with self.assertRaises(HTTPException) as ctx:
            _decode_access_token(recovery_token)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_decode_access_token_rejects_foreign_purpose_via_legacy_fallback_path(self):
        original_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        try:
            # Signed with raw SECRET_KEY (pre-Task-6 scheme) and carrying a
            # foreign purpose — old MFA/admin-recovery tokens already carried
            # a purpose claim before this commit, so the legacy path must
            # still reject them, not just the new-key path.
            legacy_mfa_token = _make_jwt(settings.SECRET_KEY, purpose=SigningPurpose.MFA_SESSION.value)
            with self.assertRaises(HTTPException) as ctx:
                _decode_access_token(legacy_mfa_token)
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = original_deadline

    def test_decode_access_token_accepts_legacy_access_token_with_no_purpose_claim(self):
        # Grandfathered: pre-this-commit access tokens never carried a
        # purpose claim at all — the legacy path must still accept those,
        # only a *foreign* purpose is rejected there.
        original_deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL
        settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=5)
        try:
            legacy_access_token = _make_jwt(settings.SECRET_KEY, purpose=None)
            token_data = _decode_access_token(legacy_access_token)
            self.assertEqual(token_data.user_id, 1)
        finally:
            settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL = original_deadline

    def test_new_key_signed_token_missing_purpose_claim_is_rejected(self):
        # Defense-in-depth: create_access_token always adds the claim, so this
        # can't happen via normal issuance — but must still be rejected if it
        # somehow did, with zero tolerance on the new-key path.
        token = _make_jwt(derive_purpose_key(SigningPurpose.JWT_ACCESS), purpose=None)
        with self.assertRaises(HTTPException) as ctx:
            _decode_access_token(token)
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
