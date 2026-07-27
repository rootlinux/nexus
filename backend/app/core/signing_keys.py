from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings


class SigningPurpose(str, Enum):
    JWT_ACCESS = "jwt_access_token"
    MFA_SESSION = "mfa_session_token"
    ADMIN_WEBAUTHN_RECOVERY = "admin_webauthn_recovery_token"
    PASSWORD_RESET = "password_reset_token"
    EMAIL_VERIFICATION = "email_verification_token"
    EMAIL_CHANGE = "email_change_token"
    FEEDBACK_ATTACHMENT_LINK = "feedback_attachment_link"


_HKDF_SALT = b"nexus-signing-key-hkdf-v1"  # fixed, versioned, not secret — domain-separates this derivation scheme


@lru_cache(maxsize=None)
def derive_purpose_key(purpose: SigningPurpose, *, length: int = 32) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=_HKDF_SALT, info=purpose.value.encode("utf-8"),
    ).derive(settings.SECRET_KEY.encode("utf-8"))


def legacy_signing_verification_allowed() -> bool:
    """Single source of truth for whether ANY legacy (raw-SECRET_KEY) fallback
    path may run right now. False when SIGNING_KEY_LEGACY_VERIFY_UNTIL is
    unset (default — new installs are never forced into a transition they
    don't need) or once that deadline has passed. Every legacy fallback path
    in this codebase — access/MFA-session/admin-recovery JWTs, password-reset/
    email-verification/email-change HMAC lookups, and the feedback-attachment
    HMAC link — calls this instead of each re-implementing the same check."""
    deadline = settings.SIGNING_KEY_LEGACY_VERIFY_UNTIL
    if deadline is None:
        return False
    return datetime.now(timezone.utc) < deadline


def decode_jwt_with_fallback(token: str, purpose: SigningPurpose, **decode_kwargs) -> tuple[dict, str]:
    """Returns (payload, verification_path) where verification_path is 'new'
    or 'legacy' — callers/tests assert on this directly rather than
    inferring it from whether decoding merely succeeded. Only an
    InvalidSignatureError (wrong key) triggers the fallback attempt — any
    other JWT error (expired, malformed, etc.) propagates immediately,
    since a different key wouldn't change that outcome."""
    try:
        payload = jwt.decode(token, derive_purpose_key(purpose), algorithms=[settings.ALGORITHM], **decode_kwargs)
        return payload, "new"
    except jwt.InvalidSignatureError:
        if not legacy_signing_verification_allowed():
            raise
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], **decode_kwargs)
        return payload, "legacy"
