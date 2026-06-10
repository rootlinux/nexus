import logging
import hmac
import mimetypes
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.deps import get_current_user, require_admin_session
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, hash_key_part
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import NeutralActionResponse
from app.schemas.feedback import FeedbackAttachmentReference, FeedbackReportRequest
from app.services.moderation_intake import BLOCKED_IMAGE_TYPES, inspect_media_bytes
from app.services.mail import build_feedback_report_message, get_mail_sender
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


def _feedback_attachment_signature(storage_key: str, expires_at: int) -> str:
    payload = f"{storage_key}:{expires_at}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), payload, sha256).hexdigest()


def _build_feedback_attachment_access_url(request: Request, storage_key: str) -> str:
    expires_at = int(datetime.now(timezone.utc).timestamp()) + (settings.FEEDBACK_ATTACHMENT_URL_TTL_MINUTES * 60)
    params = urlencode(
        {
            "expires": expires_at,
            "sig": _feedback_attachment_signature(storage_key, expires_at),
        }
    )
    relative_path = f"{settings.FEEDBACK_ATTACHMENT_URL_PREFIX.rstrip('/')}/{storage_key}?{params}"
    return urljoin(str(request.base_url), relative_path.lstrip("/"))


def _verify_feedback_attachment_access(storage_key: str, *, expires: int, sig: str) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    if expires < now:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attachment link expired")

    expected = _feedback_attachment_signature(storage_key, expires)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid attachment signature")


async def _read_attachment(file: UploadFile) -> bytes:
    try:
        return await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read the attachment.",
        ) from exc


async def _validate_and_store_attachment(request: Request, file: UploadFile) -> FeedbackAttachmentReference:
    content = await _read_attachment(file)
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

    if len(content) > settings.FEEDBACK_ATTACHMENT_MAX_BYTES:
        reason_codes.add("file_too_large")

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

    content_type = detected_type or normalized_type or "image/jpeg"
    storage_provider = _get_feedback_storage_provider()
    try:
        stored_media = await storage_provider.save_file(
            content=content,
            content_type=content_type,
            original_filename=original_filename,
        )
    except Exception:
        logger.exception("Failed to persist feedback attachment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn’t save your attachment right now.",
        ) from None

    return FeedbackAttachmentReference(
        filename=_sanitize_attachment_name(original_filename),
        content_type=content_type,
        size_bytes=len(content),
        storage_key=stored_media.storage_key,
        access_url=_build_feedback_attachment_access_url(request, stored_media.storage_key),
    )


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
) -> NeutralActionResponse:
    await enforce_rate_limits(request, _feedback_report_policies(request, current_user))
    payload, attachment_file = await _parse_feedback_payload(request)
    attachment = None
    if attachment_file is not None and attachment_file.filename:
        attachment = await _validate_and_store_attachment(request, attachment_file)

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
    current_user: User = Depends(require_admin_session),
):
    await enforce_rate_limits(request, _feedback_attachment_read_policies(request))
    storage_provider = _get_feedback_storage_provider()
    if not isinstance(storage_provider, LocalStorageProvider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback attachment downloads are not configured for this storage backend.",
        )

    _verify_feedback_attachment_access(storage_key, expires=expires, sig=sig)

    try:
        file_path = storage_provider.resolve_storage_path(storage_key)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type)
