import asyncio
import logging
import hmac
import mimetypes
from dataclasses import dataclass
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.deps import get_current_user
from app.core.authorization import Capability
from app.core.database import get_db
from app.core.signing_keys import SigningPurpose, derive_purpose_key, legacy_signing_verification_allowed
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, hash_key_part
from app.core.config import settings
from app.core.upload_limits import reject_by_content_length_hint, read_upload_within_limit
from app.services.audit import write_audit_log
from app.services.image_processing import sanitize_public_image
from app.models.feedback_report import FeedbackReport
from app.models.media_asset import MediaAsset, MediaAssetStatus, MediaAssetType
from app.models.user import User
from app.schemas.auth import NeutralActionResponse
from app.schemas.feedback import FeedbackAttachmentReference, FeedbackReportRequest
from app.services.media_assets import attach_pending_media, run_media_operation, write_media_to_storage_and_flush
from app.services.moderation_intake import BLOCKED_IMAGE_TYPES, inspect_media_bytes
from app.services.mail import build_feedback_report_message, get_mail_sender
from app.services.staff_permissions import enforce_staff_capability
from app.storage import get_storage_provider
from app.storage.local import LocalStorageProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

ALLOWED_FEEDBACK_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FEEDBACK_ATTACHMENT_FIELD = "attachment"


def _feedback_report_policies(request: Request, current_user: User) -> list[RateLimitPolicy]:
    ip_key = hash_key_part(get_client_ip(request))
    return [
        RateLimitPolicy(
            name="feedback-report-user-burst",
            limit=3,
            window_seconds=600,
            key=build_scope_key("feedback", "report", "user", current_user.id, "burst"),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="feedback-report-ip-sustained",
            limit=10,
            window_seconds=3600,
            key=build_scope_key("feedback", "report", "ip", ip_key, "sustained"),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _feedback_attachment_read_policies(request: Request) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="feedback-attachment-read-ip",
            limit=20,
            window_seconds=60,
            key=build_scope_key("feedback", "attachment", "ip", hash_key_part(get_client_ip(request))),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _feedback_attachment_error_message(reason_codes: set[str]) -> str:
    if "file_too_large" in reason_codes:
        max_size_mb = settings.FEEDBACK_ATTACHMENT_MAX_BYTES // (1024 * 1024)
        return f"Attachment must be {max_size_mb} MB or smaller."

    unsupported_reasons = {
        "invalid_png_signature",
        "invalid_jpeg_signature",
        "invalid_webp_signature",
        "invalid_png_payload",
        "invalid_webp_payload",
        "mime_mismatch",
        "extension_mismatch",
        "unsafe_file_type",
        "unsupported_file_type",
        "unsupported_detected_file_type",
    }
    if reason_codes & unsupported_reasons:
        return "Please attach a PNG, JPEG, or WebP image."

    if {"unsafe_filename", "double_extension_filename"} & reason_codes:
        return "That attachment filename is not supported. Please rename the file and try again."

    return "That attachment couldn’t be added. Please try a PNG, JPEG, or WebP image up to 5 MB."


def _sanitize_attachment_name(filename: str | None) -> str:
    candidate = Path((filename or "").strip()).name.replace("\x00", "")
    if not candidate:
        return "attachment"

    safe_chars = [
        character if character.isalnum() or character in {".", "_", "-", " "} else "_"
        for character in candidate
    ]
    normalized = "".join(safe_chars).strip(" ._-")
    return (normalized or "attachment")[:120]


def _get_feedback_storage_provider():
    storage_provider = get_storage_provider()
    if isinstance(storage_provider, LocalStorageProvider):
        return LocalStorageProvider(
            upload_dir=settings.FEEDBACK_ATTACHMENT_LOCAL_DIR,
            url_prefix=settings.FEEDBACK_ATTACHMENT_URL_PREFIX,
        )
    return storage_provider


def _feedback_attachment_signature(*, feedback_report_id: int, storage_key: str, expires: int) -> str:
    payload = f"{feedback_report_id}:{storage_key}:{expires}".encode("utf-8")
    return hmac.new(derive_purpose_key(SigningPurpose.FEEDBACK_ATTACHMENT_LINK), payload, sha256).hexdigest()


def _legacy_feedback_attachment_signature(storage_key: str, expires_at: int) -> str:
    """The exact pre-Task-6/Task-7 scheme: raw SECRET_KEY, no purpose
    derivation, no feedback_report_id binding (2 fields only). Only ever
    computed when legacy_signing_verification_allowed() is True — this is
    what a genuine link issued before this task shipped actually looks
    like; a link can never be re-signed retroactively to add the new
    binding, so this scheme is preserved exactly."""
    payload = f"{storage_key}:{expires_at}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), payload, sha256).hexdigest()


def _is_safe_storage_key(storage_key: str) -> bool:
    """Stands in for the MediaAsset DB binding new-format links require,
    for the legacy path where no such row exists at all (pre-Task-3
    feedback attachments predate MediaAsset entirely). Delegates to the
    storage provider's own resolve_storage_path — the same filename-shape
    and path-escape validation the download route already applies before
    ever opening the file."""
    storage_provider = _get_feedback_storage_provider()
    if not isinstance(storage_provider, LocalStorageProvider):
        return False
    try:
        storage_provider.resolve_storage_path(storage_key)
    except (HTTPException, ValueError):
        return False
    return True


def _is_expired(expires: int) -> bool:
    return expires < int(datetime.now(timezone.utc).timestamp())


def _build_feedback_attachment_access_url(storage_key: str, *, feedback_report_id: int) -> str:
    # Base URL is an explicit config value, never derived from the incoming
    # request (request.base_url is Host-header-derived and attacker-
    # influenceable) — see API_PUBLIC_BASE_URL.
    expires_at = int(datetime.now(timezone.utc).timestamp()) + (settings.FEEDBACK_ATTACHMENT_URL_TTL_MINUTES * 60)
    params = urlencode(
        {
            "expires": expires_at,
            "feedback_report_id": feedback_report_id,
            "sig": _feedback_attachment_signature(
                feedback_report_id=feedback_report_id, storage_key=storage_key, expires=expires_at,
            ),
        }
    )
    relative_path = f"{settings.FEEDBACK_ATTACHMENT_URL_PREFIX.rstrip('/')}/{storage_key}?{params}"
    return urljoin(settings.API_PUBLIC_BASE_URL.rstrip("/") + "/", relative_path.lstrip("/"))


@dataclass(frozen=True)
class FeedbackAttachmentVerification:
    verification_path: str  # "new" or "legacy" — asserted directly by tests/audit logging, never inferred


class FeedbackAttachmentAccessDenied(Exception):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def _verify_feedback_attachment_access(
    db: AsyncSession, *, storage_key: str, feedback_report_id: int | None, expires: int, sig: str,
) -> FeedbackAttachmentVerification:
    """feedback_report_id's presence or absence selects an entirely
    different verification scheme — it is not optional data on an
    otherwise-uniform check:

    - PRESENT: always a new-format link. Signature must be computed over
      the feedback_report_id-inclusive payload, must be unexpired, and must
      resolve to a live, ATTACHED MediaAsset row bound to exactly this
      (storage_key, feedback_report_id) pair. The DB binding is mandatory —
      the signature alone is never sufficient here, regardless of
      legacy-window state.
    - ABSENT: accepted ONLY as a genuine legacy link, and ONLY while
      legacy_signing_verification_allowed() is True. Once that window is
      closed, an absent feedback_report_id is rejected outright — never
      silently treated as "must be legacy, let it through."
    """
    if feedback_report_id is not None:
        expected_sig = _feedback_attachment_signature(
            feedback_report_id=feedback_report_id, storage_key=storage_key, expires=expires,
        )
        if not hmac.compare_digest(expected_sig, sig):
            raise FeedbackAttachmentAccessDenied(reason="invalid_signature")
        if _is_expired(expires):
            raise FeedbackAttachmentAccessDenied(reason="expired")
        asset = await db.scalar(
            select(MediaAsset).where(
                MediaAsset.storage_key == storage_key,
                MediaAsset.attached_to_type == "feedback_report",
                MediaAsset.attached_to_id == feedback_report_id,
                MediaAsset.status == MediaAssetStatus.ATTACHED,
            )
        )
        if asset is None:
            raise FeedbackAttachmentAccessDenied(reason="binding_mismatch")
        return FeedbackAttachmentVerification(verification_path="new")

    if not legacy_signing_verification_allowed():
        raise FeedbackAttachmentAccessDenied(reason="invalid_signature")

    # Legacy path: uses ONLY the exact old 2-field signature scheme — never
    # the new feedback_report_id-inclusive payload, since a genuinely old
    # link's signature was never computed over that field. No MediaAsset
    # binding check is attempted either — pre-Task-3 attachments have no
    # row to bind to, by construction. A safe storage-path check stands in.
    expected_legacy_sig = _legacy_feedback_attachment_signature(storage_key, expires)
    if not hmac.compare_digest(expected_legacy_sig, sig):
        raise FeedbackAttachmentAccessDenied(reason="invalid_signature")
    if _is_expired(expires):
        raise FeedbackAttachmentAccessDenied(reason="expired")
    if not _is_safe_storage_key(storage_key):
        raise FeedbackAttachmentAccessDenied(reason="invalid_signature")
    return FeedbackAttachmentVerification(verification_path="legacy")


async def _verify_feedback_attachment_access_or_log(
    db: AsyncSession, request: Request, *, storage_key: str, feedback_report_id: int | None,
    expires: int, sig: str, current_user: User,
) -> FeedbackAttachmentVerification:
    try:
        return await _verify_feedback_attachment_access(
            db, storage_key=storage_key, feedback_report_id=feedback_report_id, expires=expires, sig=sig,
        )
    except FeedbackAttachmentAccessDenied as exc:
        try:
            await write_audit_log(
                db, action="feedback.attachment_verification_failed", actor_user=current_user, actor_type="user",
                target_type="feedback_attachment", target_id=storage_key,
                after={"storage_key": storage_key, "feedback_report_id": feedback_report_id, "reason": exc.reason},
                request=request, success=False,
            )
            await db.commit()
        except Exception:
            # Local-only fallback logging if the audit write itself fails —
            # the 403 below is unconditional regardless, so a broken audit
            # log can never turn into an accidental grant of access.
            logger.warning("feedback_verification_failure_audit_write_failed", exc_info=True)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired attachment link.") from exc


async def require_feedback_read_with_audit(
    request: Request,
    storage_key: str,
    feedback_report_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Wraps enforce_staff_capability so a denial is audited before the
    HTTPException propagates — enforce_staff_capability itself raises
    during dependency resolution, before a route handler body would ever
    run, so logging inside the handler would never see a denial at all."""
    try:
        enforce_staff_capability(current_user, Capability.FEEDBACK_READ)
    except HTTPException as exc:
        try:
            await write_audit_log(
                db, action="feedback.attachment_access_denied", actor_user=current_user, actor_type="user",
                target_type="feedback_attachment", target_id=storage_key,
                after={"storage_key": storage_key, "feedback_report_id": feedback_report_id},
                request=request, success=False,
            )
            await db.commit()
        except Exception:
            logger.warning("feedback_access_denial_audit_write_failed", exc_info=True)
        raise exc
    return current_user


async def _validate_and_store_attachment(
    db: AsyncSession, request: Request, file: UploadFile, *, owner_user_id: int, compensation: list[str],
) -> MediaAsset:
    reject_by_content_length_hint(
        request, limit=settings.FEEDBACK_ATTACHMENT_MAX_BYTES + settings.UPLOAD_GUARD_OVERHEAD_BYTES
    )
    content = await read_upload_within_limit(file, limit=settings.FEEDBACK_ATTACHMENT_MAX_BYTES)
    detected_type = inspect_media_bytes(content).detected_content_type
    normalized_type = (file.content_type or "").strip().lower()
    original_filename = (file.filename or "").strip()
    reason_codes: set[str] = set()

    if normalized_type in BLOCKED_IMAGE_TYPES:
        reason_codes.add("unsafe_file_type")
    elif normalized_type and normalized_type not in ALLOWED_FEEDBACK_ATTACHMENT_TYPES:
        reason_codes.add("unsupported_file_type")

    if detected_type is None:
        reason_codes.add("unsupported_detected_file_type")
    elif detected_type not in ALLOWED_FEEDBACK_ATTACHMENT_TYPES:
        reason_codes.add("unsupported_detected_file_type")

    # Oversize is now rejected as 413 by read_upload_within_limit above, before this
    # function's body ever runs — no "file_too_large" reason code is reachable here
    # anymore (Round 2, Task 1).

    if normalized_type and detected_type and normalized_type != detected_type:
        reason_codes.add("mime_mismatch")

    if any(separator in original_filename for separator in ("/", "\\", "\x00")):
        reason_codes.add("unsafe_filename")
    if len(Path(original_filename).suffixes) > 1:
        reason_codes.add("double_extension_filename")

    if reason_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_feedback_attachment_error_message(reason_codes),
        )

    # Decode + re-encode (strips EXIF/PNG-chunk metadata, rejects animated/unsupported
    # formats via Pillow's own post-decode detection) — never store the raw upload.
    # Feedback attachments are staff-only rather than literally "public," but can still
    # carry sensitive EXIF (e.g. a screenshot with location data).
    sanitized = await asyncio.to_thread(sanitize_public_image, content, detected_content_type=detected_type)
    storage_provider = _get_feedback_storage_provider()
    try:
        asset = await write_media_to_storage_and_flush(
            db, owner_user_id=owner_user_id, media_type=MediaAssetType.FEEDBACK_ATTACHMENT,
            content=sanitized.content, content_type=sanitized.content_type,
            storage_provider=storage_provider, original_filename=original_filename,
        )
    except Exception:
        logger.exception("Failed to persist feedback attachment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn’t save your attachment right now.",
        ) from None
    compensation.append(asset.storage_key)
    return asset


async def _parse_feedback_payload(request: Request) -> tuple[FeedbackReportRequest, UploadFile | None]:
    content_type = request.headers.get("content-type", "").lower()

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            payload = FeedbackReportRequest.model_validate(
                {
                    "title": form.get("title"),
                    "description": form.get("description"),
                    "current_path": form.get("current_path"),
                    "username": form.get("username"),
                    "device_info": form.get("device_info"),
                    "contact_email": form.get("contact_email"),
                    "current_url": form.get("current_url"),
                    "user_agent": form.get("user_agent"),
                    "standalone_mode": form.get("standalone_mode"),
                    "occurred_at": form.get("occurred_at"),
                    "app_version": form.get("app_version"),
                }
            )
            attachment = form.get(FEEDBACK_ATTACHMENT_FIELD)
            return payload, attachment if isinstance(attachment, StarletteUploadFile) else None

        payload = FeedbackReportRequest.model_validate(await request.json())
        return payload, None
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc


@router.post("/report", response_model=NeutralActionResponse)
async def submit_feedback_report(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NeutralActionResponse:
    await enforce_rate_limits(request, _feedback_report_policies(request, current_user))
    payload, attachment_file = await _parse_feedback_payload(request)
    has_attachment = attachment_file is not None and bool(attachment_file.filename)

    async def _op(compensation: list[str]) -> tuple[FeedbackReport, FeedbackAttachmentReference | None]:
        feedback_report = FeedbackReport(submitter_user_id=current_user.id)
        db.add(feedback_report)
        await db.flush()

        attachment_ref = None
        if has_attachment:
            asset = await _validate_and_store_attachment(
                db, request, attachment_file, owner_user_id=current_user.id, compensation=compensation,
            )
            await attach_pending_media(
                db, storage_key=asset.storage_key, owner_user_id=current_user.id,
                attached_to_type="feedback_report", attached_to_id=feedback_report.id,
            )
            attachment_ref = FeedbackAttachmentReference(
                filename=_sanitize_attachment_name((attachment_file.filename or "").strip()),
                content_type=asset.content_type,
                size_bytes=asset.file_size_bytes,
                storage_key=asset.storage_key,
                access_url=_build_feedback_attachment_access_url(
                    asset.storage_key, feedback_report_id=feedback_report.id,
                ),
            )
        return feedback_report, attachment_ref

    _feedback_report, attachment = await run_media_operation(
        db, _op, storage_provider=_get_feedback_storage_provider(),
    )

    submitted_at = datetime.now(timezone.utc).isoformat()
    message = build_feedback_report_message(
        title=payload.title,
        description=payload.description,
        username=payload.username or current_user.username,
        account_email=current_user.email,
        contact_email=payload.contact_email,
        current_path=payload.current_path,
        current_url=payload.current_url,
        device_info=payload.device_info,
        user_agent=payload.user_agent or request.headers.get("user-agent"),
        standalone_mode=payload.standalone_mode,
        occurred_at=payload.occurred_at,
        submitted_at=submitted_at,
        user_id=current_user.id,
        app_version=payload.app_version,
        attachment=attachment,
    )

    try:
        await get_mail_sender().send(message)
    except Exception:
        logger.exception(
            "Failed to deliver beta feedback report",
            extra={"user_id": current_user.id, "request_id": getattr(request.state, "request_id", None)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Couldn’t send your report right now.",
        ) from None

    return NeutralActionResponse(message="Your report was sent.")


@router.get("/attachments/{storage_key}")
async def download_feedback_attachment(
    request: Request,
    storage_key: str,
    expires: int,
    sig: str,
    feedback_report_id: int | None = None,
    current_user: User = Depends(require_feedback_read_with_audit),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _feedback_attachment_read_policies(request))
    storage_provider = _get_feedback_storage_provider()
    if not isinstance(storage_provider, LocalStorageProvider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback attachment downloads are not configured for this storage backend.",
        )

    verification = await _verify_feedback_attachment_access_or_log(
        db, request, storage_key=storage_key, feedback_report_id=feedback_report_id,
        expires=expires, sig=sig, current_user=current_user,
    )

    try:
        file_path = storage_provider.resolve_storage_path(storage_key)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    await write_audit_log(
        db, action="feedback.attachment_downloaded", actor_user=current_user, actor_type="user",
        target_type="feedback_attachment", target_id=storage_key,
        after={"feedback_report_id": feedback_report_id, "storage_key": storage_key,
               "verification_path": verification.verification_path},
        request=request, success=True,
    )
    await db.commit()

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type)
