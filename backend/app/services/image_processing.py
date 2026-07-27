from dataclasses import dataclass
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

# Prevent decompression bombs and pixel DoS from user-uploaded images.
# Centralized here (was an import-time side effect in users.py).
Image.MAX_IMAGE_PIXELS = 50_000_000

PROFILE_IMAGE_BACKGROUND = "#0d0e12"


@dataclass(frozen=True)
class SanitizedImage:
    content: bytes
    content_type: str


def _image_has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        alpha = image.getchannel("A")
        minimum_alpha, maximum_alpha = alpha.getextrema()
        return minimum_alpha < 255 or maximum_alpha < 255

    if image.mode == "P":
        transparency = image.info.get("transparency")
        if transparency is None:
            return False
        if isinstance(transparency, bytes):
            return any(alpha < 255 for alpha in transparency)
        if isinstance(transparency, int):
            return transparency in image.getdata()

    return False


def sanitize_profile_image(content: bytes) -> SanitizedImage:
    """Avatar/cover path: force-flattened to JPEG on a solid background.
    Behavior unchanged from the pre-Round-2 implementation this replaces —
    only moved into a shared module."""
    try:
        with Image.open(BytesIO(content)) as uploaded_image:
            image = ImageOps.exif_transpose(uploaded_image)

            if _image_has_transparency(image):
                background = Image.new("RGBA", image.size, PROFILE_IMAGE_BACKGROUND)
                image = Image.alpha_composite(background, image.convert("RGBA"))

            rgb_image = image.convert("RGB")
            output = BytesIO()
            rgb_image.save(output, format="JPEG", quality=settings.IMAGE_REENCODE_JPEG_QUALITY, optimize=True)
            return SanitizedImage(content=output.getvalue(), content_type="image/jpeg")
    except (Image.DecompressionBombError, ValueError) as exc:
        # Covers decompression bombs and excessive pixel dimensions (MAX_IMAGE_PIXELS)
        raise HTTPException(status_code=400, detail="Image dimensions too large") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise HTTPException(status_code=400, detail="Failed to process uploaded file") from exc


_ALLOWED_PUBLIC_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def reject_if_animated_or_unsupported(img: Image.Image) -> None:
    """Checks Pillow's own post-decode format/frame introspection, not the
    client-declared Content-Type or filename — a renamed .gif served as
    image/jpeg still decodes with img.format=='GIF' and gets caught here.
    Covers animated GIF, animated WebP, and APNG uniformly, since Pillow
    exposes is_animated/n_frames the same way for all three formats it can
    decode with animation support."""
    if img.format not in _ALLOWED_PUBLIC_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail=f"{img.format or 'unknown'} images are not supported.")
    if getattr(img, "n_frames", 1) > 1 or getattr(img, "is_animated", False):
        raise HTTPException(status_code=400, detail="Animated images are not supported.")


def sanitize_public_image(content: bytes, *, detected_content_type: str | None = None) -> SanitizedImage:
    """Post-image / feedback-attachment path: re-encodes in the SAME format,
    preserving transparency (unlike the avatar/cover path). `detected_content_type`
    is accepted for call-site compatibility but the actual save format always
    trusts Pillow's own post-decode detection (img.format), never the caller's
    hint — that's what makes this resistant to a renamed file or spoofed MIME."""
    try:
        with Image.open(BytesIO(content)) as img:
            reject_if_animated_or_unsupported(img)
            target_format = img.format
            img = ImageOps.exif_transpose(img)
            save_kwargs: dict = {"optimize": True}
            if target_format == "JPEG":
                img = img.convert("RGB")
                save_kwargs["quality"] = settings.IMAGE_REENCODE_JPEG_QUALITY
            elif target_format == "WEBP":
                save_kwargs["quality"] = settings.IMAGE_REENCODE_WEBP_QUALITY
            if settings.IMAGE_PRESERVE_ICC_PROFILE and "icc_profile" in img.info:
                save_kwargs["icc_profile"] = img.info["icc_profile"]
            # Deliberately no exif=... / pnginfo=... kwargs: Pillow only embeds those
            # blocks when explicitly supplied, so omitting them strips EXIF (GPS,
            # device, comments) and PNG tEXt/iTXt/zTXt chunks.
            output = BytesIO()
            img.save(output, format=target_format, **save_kwargs)
        return SanitizedImage(content=output.getvalue(), content_type=f"image/{target_format.lower()}")
    except HTTPException:
        raise
    except Image.DecompressionBombError as exc:
        raise HTTPException(status_code=400, detail="Image dimensions too large") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Failed to process uploaded file") from exc
