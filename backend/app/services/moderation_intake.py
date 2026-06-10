from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.moderation_signal import (
    ModerationDetectionStatus,
    ModerationReviewStatus,
    ModerationSignal,
    ModerationSurface,
)


PRODUCT_BLOCK_MESSAGE = "This content violates platform policy."
PRODUCT_REVIEW_MESSAGE = "This update needs review before it can be used."
PRODUCT_PUBLISH_MESSAGE = "This content could not be published."
PRODUCT_MEDIA_REVIEW_MESSAGE = "This upload needs review before it can be used."
PRODUCT_MEDIA_UPLOAD_FAILURE_MESSAGE = "This image could not be uploaded."

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
BLOCKED_IMAGE_TYPES = {"image/svg+xml", "image/svg", "application/svg+xml"}
ALLOWED_IMAGE_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/gif": {".gif"},
    "image/webp": {".webp"},
}
BLOCKED_IMAGE_EXTENSIONS = {".svg", ".svgz", ".exe", ".js", ".html", ".php"}

BLOCKED_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("sexual_content", re.compile(r"\b(onlyfans|camgirl|nudes?|nsfw|escort)\b", re.IGNORECASE), 95),
    ("abusive_harassment", re.compile(r"\b(kys|kill yourself)\b", re.IGNORECASE), 95),
    ("spam_scam", re.compile(r"\b(free money|crypto giveaway|guaranteed returns?)\b", re.IGNORECASE), 90),
)
SUSPICIOUS_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("spam_terms", re.compile(r"\b(telegram|whatsapp|dm me|promo code|follow back)\b", re.IGNORECASE), 60),
    ("sexual_hint", re.compile(r"\b(sexy|hot singles|hookup)\b", re.IGNORECASE), 55),
    ("abuse_hint", re.compile(r"\b(stupid|idiot|moron)\b", re.IGNORECASE), 45),
)

# Leetspeak substitution table: digits and symbols → their letter equivalents
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a",
    "@": "a", "5": "s", "$": "s", "7": "t", "!": "i",
})

# Patterns matched against the compacted+normalised form (no spaces, no leetspeak).
# Do NOT use \b here; the string has no word boundaries after space removal.
BLOCKED_EVASION_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("sexual_content", re.compile(r"onlyfans|camgirl|nudes?|nsfw|escort"), 95),
    ("abusive_harassment", re.compile(r"kys|killyourself"), 95),
    ("spam_scam", re.compile(r"freemoney|cryptogiveaway|guaranteedreturns?"), 90),
)


def _normalize_for_evasion(text: str) -> str:
    """Lowercase, apply leetspeak substitutions, then strip all non-alphanumeric chars.

    The result is used only for evasion pattern matching, never stored or displayed.
    Example: "k1ll y0urs3lf" → "killyourself"
    """
    return re.sub(r"[^a-z0-9]", "", text.lower().translate(_LEET_MAP))
SUSPICIOUS_TLDS = {".ru", ".xyz", ".click", ".top", ".work", ".gq"}
MEDIA_SURFACES = {
    ModerationSurface.PROFILE_AVATAR,
    ModerationSurface.PROFILE_COVER,
    ModerationSurface.POST_MEDIA,
    ModerationSurface.DM_MEDIA,
}


@dataclass
class ModerationAssessment:
    surface_type: ModerationSurface
    detection_status: ModerationDetectionStatus
    reason_codes: list[str]
    reason_summary: str
    risk_score: int
    content_preview: str | None = None
    media_url: str | None = None
    canonical_content_type: str | None = None

    @property
    def is_blocked(self) -> bool:
        return self.detection_status == ModerationDetectionStatus.BLOCKED

    @property
    def requires_review(self) -> bool:
        return self.detection_status == ModerationDetectionStatus.SUSPICIOUS


@dataclass
class MediaInspection:
    detected_content_type: str | None
    width: int | None
    height: int | None
    issues: list[str]
    is_animated: bool = False


def _truncate_preview(value: str | None, limit: int = 280) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:limit]


def _summarize(reasons: list[str], fallback: str) -> str:
    if not reasons:
        return fallback
    summary = ", ".join(reason.replace("_", " ") for reason in reasons[:3])
    return summary[:500]


def _is_media_surface(surface_type: ModerationSurface) -> bool:
    return surface_type in MEDIA_SURFACES


def _read_be_u32(content: bytes, offset: int) -> int:
    return struct.unpack(">I", content[offset : offset + 4])[0]


def _read_le_u16(content: bytes, offset: int) -> int:
    return struct.unpack("<H", content[offset : offset + 2])[0]


def _inspect_png(content: bytes) -> MediaInspection:
    issues: list[str] = []
    if len(content) < 33 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaInspection("image/png", None, None, ["invalid_png_signature"])

    offset = 8
    width = None
    height = None
    idat_chunks: list[bytes] = []
    saw_iend = False

    while offset + 12 <= len(content):
        chunk_length = _read_be_u32(content, offset)
        chunk_type = content[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        crc_end = data_end + 4
        if crc_end > len(content):
            issues.append("truncated_png_chunk")
            break

        chunk_data = content[data_start:data_end]
        if chunk_type == b"IHDR":
            if chunk_length != 13:
                issues.append("invalid_png_ihdr")
                break
            width = _read_be_u32(chunk_data, 0)
            height = _read_be_u32(chunk_data, 4)
            if width <= 0 or height <= 0:
                issues.append("invalid_png_dimensions")
                break
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            saw_iend = True
            offset = crc_end
            break

        offset = crc_end

    if not saw_iend:
        issues.append("missing_png_end")

    if idat_chunks:
        try:
            zlib.decompress(b"".join(idat_chunks))
        except Exception:
            issues.append("invalid_png_payload")
    else:
        issues.append("missing_png_payload")

    return MediaInspection("image/png", width, height, sorted(set(issues)))


def _skip_gif_sub_blocks(content: bytes, offset: int) -> int | None:
    while offset < len(content):
        block_size = content[offset]
        offset += 1
        if block_size == 0:
            return offset
        offset += block_size
        if offset > len(content):
            return None
    return None


def _inspect_gif(content: bytes) -> MediaInspection:
    issues: list[str] = []
    if len(content) < 14 or content[:6] not in {b"GIF87a", b"GIF89a"}:
        return MediaInspection("image/gif", None, None, ["invalid_gif_signature"])

    width = _read_le_u16(content, 6)
    height = _read_le_u16(content, 8)
    if width <= 0 or height <= 0:
        issues.append("invalid_gif_dimensions")

    offset = 13
    packed = content[10]
    if packed & 0x80:
        global_table_size = 3 * (2 ** ((packed & 0x07) + 1))
        offset += global_table_size

    frame_count = 0
    trailer_found = False

    while offset < len(content):
        block_type = content[offset]
        offset += 1

        if block_type == 0x3B:
            trailer_found = True
            break

        if block_type == 0x2C:
            frame_count += 1
            if offset + 9 > len(content):
                issues.append("truncated_gif_frame")
                break
            packed = content[offset + 8]
            offset += 9
            if packed & 0x80:
                local_table_size = 3 * (2 ** ((packed & 0x07) + 1))
                offset += local_table_size
            if offset >= len(content):
                issues.append("truncated_gif_frame")
                break
            offset += 1  # lzw min code size
            next_offset = _skip_gif_sub_blocks(content, offset)
            if next_offset is None:
                issues.append("invalid_gif_payload")
                break
            offset = next_offset
            continue

        if block_type == 0x21:
            if offset >= len(content):
                issues.append("truncated_gif_extension")
                break
            offset += 1  # extension label
            next_offset = _skip_gif_sub_blocks(content, offset)
            if next_offset is None:
                issues.append("invalid_gif_extension")
                break
            offset = next_offset
            continue

        issues.append("unknown_gif_block")
        break

    if not trailer_found:
        issues.append("missing_gif_end")
    if frame_count == 0:
        issues.append("missing_gif_frame")

    return MediaInspection("image/gif", width, height, sorted(set(issues)), is_animated=frame_count > 1)


def _inspect_jpeg(content: bytes) -> MediaInspection:
    issues: list[str] = []
    if len(content) < 4 or not content.startswith(b"\xFF\xD8"):
        return MediaInspection("image/jpeg", None, None, ["invalid_jpeg_signature"])

    width = None
    height = None
    offset = 2
    saw_end = False

    while offset < len(content):
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            break
        marker = content[offset]
        offset += 1

        if marker == 0xD9:
            saw_end = True
            break

        if marker in {0x01, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7}:
            continue

        if offset + 2 > len(content):
            issues.append("truncated_jpeg_segment")
            break
        segment_length = struct.unpack(">H", content[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(content):
            issues.append("invalid_jpeg_segment")
            break

        segment_start = offset + 2
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                issues.append("invalid_jpeg_frame")
                break
            height = struct.unpack(">H", content[segment_start + 1 : segment_start + 3])[0]
            width = struct.unpack(">H", content[segment_start + 3 : segment_start + 5])[0]
            if width <= 0 or height <= 0:
                issues.append("invalid_jpeg_dimensions")
                break

        if marker == 0xDA:
            if not content.endswith(b"\xFF\xD9"):
                issues.append("missing_jpeg_end")
            saw_end = content.endswith(b"\xFF\xD9")
            break

        offset += segment_length

    if width is None or height is None:
        issues.append("missing_jpeg_dimensions")
    if not saw_end:
        issues.append("missing_jpeg_end")

    return MediaInspection("image/jpeg", width, height, sorted(set(issues)))


def _inspect_webp(content: bytes) -> MediaInspection:
    issues: list[str] = []
    if len(content) < 30 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        return MediaInspection("image/webp", None, None, ["invalid_webp_signature"])

    declared_size = struct.unpack("<I", content[4:8])[0] + 8
    if declared_size > len(content):
        issues.append("truncated_webp_payload")

    chunk_type = content[12:16]
    width = None
    height = None
    is_animated = False

    if chunk_type == b"VP8X" and len(content) >= 30:
        features = content[20]
        is_animated = bool(features & 0x02)
        width = int.from_bytes(content[24:27], "little") + 1
        height = int.from_bytes(content[27:30], "little") + 1
    elif chunk_type == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
        b0, b1, b2, b3 = content[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
    elif chunk_type == b"VP8 " and len(content) >= 30:
        if content[23:26] != b"\x9d\x01\x2a":
            issues.append("invalid_webp_payload")
        else:
            width = struct.unpack("<H", content[26:28])[0] & 0x3FFF
            height = struct.unpack("<H", content[28:30])[0] & 0x3FFF
    else:
        issues.append("unsupported_webp_chunk")

    if width is None or height is None or width <= 0 or height <= 0:
        issues.append("invalid_webp_dimensions")

    return MediaInspection("image/webp", width, height, sorted(set(issues)), is_animated=is_animated)


def inspect_media_bytes(content: bytes) -> MediaInspection:
    if not content:
        return MediaInspection(None, None, None, ["empty_file"])
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return _inspect_png(content)
    if content[:6] in {b"GIF87a", b"GIF89a"}:
        return _inspect_gif(content)
    if content.startswith(b"\xFF\xD8"):
        return _inspect_jpeg(content)
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return _inspect_webp(content)
    return MediaInspection(None, None, None, ["invalid_image_signature"])


def _build_media_preview(
    original_filename: str | None,
    detected_content_type: str | None,
    width: int | None,
    height: int | None,
    content_size: int,
    *,
    is_animated: bool,
) -> str | None:
    parts = []
    normalized_name = (original_filename or "").strip()
    if normalized_name:
        parts.append(normalized_name[:80])
    if detected_content_type:
        parts.append(detected_content_type)
    if width and height:
        parts.append(f"{width}x{height}")
    parts.append(f"{content_size} bytes")
    if is_animated:
        parts.append("animated")
    return _truncate_preview(" · ".join(parts), limit=160)


def assess_text_content(surface_type: ModerationSurface, text: str | None) -> ModerationAssessment:
    normalized = (text or "").strip()
    reasons: list[str] = []
    risk_score = 0
    status_value = ModerationDetectionStatus.CLEAN

    if not normalized:
        if surface_type in {ModerationSurface.PROFILE_DISPLAY_NAME, ModerationSurface.PROFILE_BIO}:
            return ModerationAssessment(
                surface_type=surface_type,
                detection_status=ModerationDetectionStatus.SUSPICIOUS,
                reason_codes=["empty_or_low_signal"],
                reason_summary="empty or low signal text",
                risk_score=25,
                content_preview=None,
            )
        return ModerationAssessment(
            surface_type=surface_type,
            detection_status=ModerationDetectionStatus.CLEAN,
            reason_codes=[],
            reason_summary="clean",
            risk_score=0,
            content_preview=None,
        )

    lowered = normalized.lower()
    evasion_form = _normalize_for_evasion(normalized)

    for code, pattern, score in BLOCKED_TEXT_PATTERNS:
        if pattern.search(normalized):
            reasons.append(code)
            risk_score = max(risk_score, score)
            status_value = ModerationDetectionStatus.BLOCKED

    for code, pattern, score in BLOCKED_EVASION_PATTERNS:
        if code not in reasons and pattern.search(evasion_form):
            reasons.append(code)
            risk_score = max(risk_score, score)
            status_value = ModerationDetectionStatus.BLOCKED

    if len(re.findall(r"https?://", lowered)) >= 2:
        reasons.append("multi_link_spam")
        risk_score = max(risk_score, 75)
        status_value = ModerationDetectionStatus.BLOCKED

    repeated_words = re.findall(r"\b(\w{3,})\b(?:\s+\1\b){2,}", lowered)
    if repeated_words:
        reasons.append("repeated_text_spam")
        risk_score = max(risk_score, 88)
        status_value = ModerationDetectionStatus.BLOCKED

    unique_chars = {char for char in lowered if not char.isspace()}
    if len(unique_chars) <= 2 and len(lowered.replace(" ", "")) >= 8:
        reasons.append("garbage_text")
        risk_score = max(risk_score, 70)
        status_value = ModerationDetectionStatus.SUSPICIOUS

    for code, pattern, score in SUSPICIOUS_TEXT_PATTERNS:
        if pattern.search(normalized):
            reasons.append(code)
            risk_score = max(risk_score, score)
            if status_value != ModerationDetectionStatus.BLOCKED:
                status_value = ModerationDetectionStatus.SUSPICIOUS

    if re.search(r"(.)\1{7,}", normalized):
        reasons.append("excessive_character_repeat")
        risk_score = max(risk_score, 60)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    if re.search(r"https?://\d{1,3}(?:\.\d{1,3}){3}", lowered):
        reasons.append("ip_link")
        risk_score = max(risk_score, 72)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    return ModerationAssessment(
        surface_type=surface_type,
        detection_status=status_value,
        reason_codes=sorted(set(reasons)),
        reason_summary=_summarize(sorted(set(reasons)), "clean"),
        risk_score=risk_score,
        content_preview=_truncate_preview(normalized),
    )


def assess_media_input(
    surface_type: ModerationSurface,
    *,
    content_type: str | None,
    original_filename: str | None,
    content: bytes | None,
    content_size: int,
    max_size: int,
    media_url: str | None = None,
) -> ModerationAssessment:
    reasons: list[str] = []
    risk_score = 0
    status_value = ModerationDetectionStatus.CLEAN

    normalized_type = (content_type or "").strip().lower()
    original_path = Path((original_filename or "").strip())
    suffix = original_path.suffix.lower()
    suffixes = [part.lower() for part in original_path.suffixes]
    inspection = inspect_media_bytes(content or b"")
    detected_type = inspection.detected_content_type

    if normalized_type in BLOCKED_IMAGE_TYPES or suffix in BLOCKED_IMAGE_EXTENSIONS:
        reasons.append("unsafe_file_type")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if normalized_type and normalized_type not in ALLOWED_IMAGE_TYPES:
        reasons.append("unsupported_file_type")
        risk_score = max(risk_score, 90)
        status_value = ModerationDetectionStatus.BLOCKED

    if detected_type is None:
        reasons.extend(inspection.issues or ["invalid_image_signature"])
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED
    elif detected_type not in ALLOWED_IMAGE_TYPES:
        reasons.append("unsupported_detected_file_type")
        risk_score = max(risk_score, 90)
        status_value = ModerationDetectionStatus.BLOCKED

    if content_size > max_size:
        reasons.append("file_too_large")
        risk_score = max(risk_score, 90)
        status_value = ModerationDetectionStatus.BLOCKED

    if normalized_type and detected_type and normalized_type != detected_type:
        reasons.append("mime_mismatch")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if suffix and detected_type in ALLOWED_IMAGE_EXTENSIONS and suffix not in ALLOWED_IMAGE_EXTENSIONS[detected_type]:
        reasons.append("extension_mismatch")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if inspection.issues:
        reasons.extend(inspection.issues)
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    normalized_name = (original_filename or "").strip()
    lowered_name = normalized_name.lower()
    if any(separator in normalized_name for separator in ("/", "\\", "\x00")):
        reasons.append("unsafe_filename")
        risk_score = max(risk_score, 70)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    if len(suffixes) > 1:
        reasons.append("double_extension_filename")
        risk_score = max(risk_score, 65)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    if any(term in lowered_name for term in ("nsfw", "nude", "onlyfans", "spam", "crypto")):
        reasons.append("suspicious_filename")
        risk_score = max(risk_score, 65)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    if inspection.width and inspection.height:
        aspect_ratio = max(inspection.width / inspection.height, inspection.height / inspection.width)
        if aspect_ratio >= 6:
            reasons.append("extreme_aspect_ratio")
            risk_score = max(risk_score, 58)
            if status_value != ModerationDetectionStatus.BLOCKED:
                status_value = ModerationDetectionStatus.SUSPICIOUS
        megapixels = (inspection.width * inspection.height) / 1_000_000
        if megapixels > 40:
            reasons.append("oversized_pixel_dimensions")
            risk_score = max(risk_score, 90)
            status_value = ModerationDetectionStatus.BLOCKED
        elif megapixels > 20:
            reasons.append("large_pixel_dimensions")
            risk_score = max(risk_score, 60)
            if status_value != ModerationDetectionStatus.BLOCKED:
                status_value = ModerationDetectionStatus.SUSPICIOUS

    if inspection.is_animated and surface_type in {ModerationSurface.PROFILE_AVATAR, ModerationSurface.PROFILE_COVER}:
        reasons.append("animated_profile_media")
        risk_score = max(risk_score, 60)
        if status_value != ModerationDetectionStatus.BLOCKED:
            status_value = ModerationDetectionStatus.SUSPICIOUS

    return ModerationAssessment(
        surface_type=surface_type,
        detection_status=status_value,
        reason_codes=sorted(set(reasons)),
        reason_summary=_summarize(sorted(set(reasons)), "clean"),
        risk_score=risk_score,
        content_preview=_build_media_preview(
            original_filename,
            detected_type,
            inspection.width,
            inspection.height,
            content_size,
            is_animated=inspection.is_animated,
        ),
        media_url=media_url,
        canonical_content_type=detected_type or normalized_type or None,
    )


def assess_media_url(surface_type: ModerationSurface, media_url: str | None) -> ModerationAssessment:
    normalized = (media_url or "").strip()
    if not normalized:
        return ModerationAssessment(
            surface_type=surface_type,
            detection_status=ModerationDetectionStatus.CLEAN,
            reason_codes=[],
            reason_summary="clean",
            risk_score=0,
            media_url=None,
        )

    reasons: list[str] = []
    risk_score = 0
    status_value = ModerationDetectionStatus.CLEAN
    parsed = urlparse(normalized)
    suffix = Path(parsed.path).suffix.lower()
    upload_prefix = settings.LOCAL_UPLOAD_URL_PREFIX.rstrip("/") or "/uploads"
    normalized_path = parsed.path or normalized
    is_relative_upload = normalized.startswith(upload_prefix) or normalized_path.startswith(upload_prefix)

    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        reasons.append("unsupported_media_scheme")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if not parsed.scheme and parsed.netloc:
        reasons.append("protocol_relative_media_url")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if parsed.scheme in {"http", "https"}:
        reasons.append("external_media_url_not_allowed")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if not is_relative_upload:
        reasons.append("untrusted_media_path")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if suffix in BLOCKED_IMAGE_EXTENSIONS:
        reasons.append("unsafe_media_extension")
        risk_score = max(risk_score, 95)
        status_value = ModerationDetectionStatus.BLOCKED

    if parsed.netloc:
        netloc = parsed.netloc.lower()
        for tld in SUSPICIOUS_TLDS:
            if netloc.endswith(tld):
                reasons.append("suspicious_media_host")
                risk_score = max(risk_score, 55)
                if status_value != ModerationDetectionStatus.BLOCKED:
                    status_value = ModerationDetectionStatus.SUSPICIOUS
                break

    return ModerationAssessment(
        surface_type=surface_type,
        detection_status=status_value,
        reason_codes=sorted(set(reasons)),
        reason_summary=_summarize(sorted(set(reasons)), "clean"),
        risk_score=risk_score,
        media_url=normalized,
    )


async def create_moderation_signal(
    db: AsyncSession,
    *,
    user_id: int,
    assessment: ModerationAssessment,
    post_id: int | None = None,
    dm_message_id: int | None = None,
    review_status: ModerationReviewStatus | None = None,
) -> ModerationSignal:
    status_value = review_status
    resolved_at = None
    resolution_action = None

    if status_value is None:
        if assessment.detection_status == ModerationDetectionStatus.CLEAN:
            status_value = ModerationReviewStatus.RESOLVED
            resolved_at = datetime.now(timezone.utc)
            resolution_action = "auto_clean"
        else:
            status_value = ModerationReviewStatus.OPEN

    signal = ModerationSignal(
        user_id=user_id,
        post_id=post_id,
        dm_message_id=dm_message_id,
        surface_type=assessment.surface_type,
        detection_status=assessment.detection_status,
        review_status=status_value,
        reason_codes=assessment.reason_codes,
        reason_summary=assessment.reason_summary,
        risk_score=assessment.risk_score,
        content_preview=assessment.content_preview,
        media_url=assessment.media_url,
        resolved_at=resolved_at,
        resolution_action=resolution_action,
    )
    db.add(signal)
    await db.flush()
    return signal


async def find_signal_by_media_url(
    db: AsyncSession,
    *,
    user_id: int,
    surface_type: ModerationSurface,
    media_url: str,
) -> ModerationSignal | None:
    result = await db.execute(
        select(ModerationSignal)
        .where(
            ModerationSignal.user_id == user_id,
            ModerationSignal.surface_type == surface_type,
            ModerationSignal.media_url == media_url,
        )
        .order_by(ModerationSignal.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def raise_blocked_content_error(surface_type: ModerationSurface) -> None:
    detail = PRODUCT_BLOCK_MESSAGE
    if surface_type in {ModerationSurface.POST_TEXT, ModerationSurface.POST_MEDIA, ModerationSurface.DM_TEXT, ModerationSurface.DM_MEDIA}:
        detail = PRODUCT_PUBLISH_MESSAGE
    if surface_type in {
        ModerationSurface.PROFILE_AVATAR,
        ModerationSurface.PROFILE_COVER,
        ModerationSurface.PROFILE_DISPLAY_NAME,
        ModerationSurface.PROFILE_BIO,
    }:
        detail = PRODUCT_MEDIA_UPLOAD_FAILURE_MESSAGE if surface_type in {ModerationSurface.PROFILE_AVATAR, ModerationSurface.PROFILE_COVER} else PRODUCT_BLOCK_MESSAGE
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def raise_review_required_error(surface_type: ModerationSurface) -> None:
    detail = PRODUCT_MEDIA_REVIEW_MESSAGE if _is_media_surface(surface_type) else PRODUCT_REVIEW_MESSAGE
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
