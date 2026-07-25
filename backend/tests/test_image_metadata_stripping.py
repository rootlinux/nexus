import os
import secrets
import unittest
from io import BytesIO

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from fastapi import HTTPException

from app.core.config import settings
from app.services.image_processing import (
    reject_if_animated_or_unsupported,
    sanitize_profile_image,
    sanitize_public_image,
)


def _jpeg_with_gps_and_comment() -> bytes:
    img = Image.new("RGB", (4, 3), (200, 50, 50))
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (10, 1), 3: "E", 4: (20, 1)}  # GPSInfo IFD
    exif[0x9286] = "a private comment"  # UserComment
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _png_with_text_chunks() -> bytes:
    img = Image.new("RGB", (3, 3), (10, 20, 30))
    info = PngInfo()
    info.add_text("Comment", "hello from a test")
    info.add_text("Author", "someone")
    buf = BytesIO()
    img.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


def _jpeg_with_orientation(orientation: int) -> bytes:
    # A visually asymmetric image (red stripe on the left) so a rotation is detectable.
    img = Image.new("RGB", (6, 4), (255, 255, 255))
    for y in range(4):
        img.putpixel((0, y), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _jpeg_with_icc_profile() -> bytes:
    img = Image.new("RGB", (2, 2), (1, 2, 3))
    # A syntactically-valid-enough ICC profile blob is not required for this
    # test — Pillow only needs a bytes payload present under "icc_profile" to
    # exercise the preserve/strip branch; a real-encoder-produced profile
    # isn't necessary for testing that presence/absence is controlled by
    # settings.IMAGE_PRESERVE_ICC_PROFILE.
    fake_icc = b"\x00\x00\x02\x10" + b"FAKEPROFILEDATA" * 8
    buf = BytesIO()
    img.save(buf, format="JPEG", icc_profile=fake_icc)
    return buf.getvalue()


def _animated_gif() -> bytes:
    frame1 = Image.new("RGB", (4, 4), (255, 0, 0))
    frame2 = Image.new("RGB", (4, 4), (0, 255, 0))
    buf = BytesIO()
    frame1.save(buf, format="GIF", save_all=True, append_images=[frame2], duration=100, loop=0)
    return buf.getvalue()


def _static_gif() -> bytes:
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def _animated_webp() -> bytes:
    frame1 = Image.new("RGB", (4, 4), (255, 0, 0))
    frame2 = Image.new("RGB", (4, 4), (0, 255, 0))
    buf = BytesIO()
    frame1.save(buf, format="WEBP", save_all=True, append_images=[frame2], duration=100, loop=0)
    return buf.getvalue()


def _static_webp() -> bytes:
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def _static_png() -> bytes:
    img = Image.new("RGB", (4, 4), (10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _static_jpeg() -> bytes:
    img = Image.new("RGB", (4, 4), (10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class MetadataStrippingTests(unittest.TestCase):
    def test_jpeg_gps_and_comment_stripped_via_sanitize_public_image(self):
        content = _jpeg_with_gps_and_comment()
        sanitized = sanitize_public_image(content)
        result = Image.open(BytesIO(sanitized.content))
        exif = result.getexif()
        self.assertNotIn(0x8825, exif)  # GPSInfo
        self.assertNotIn(0x9286, exif)  # UserComment
        self.assertEqual(len(dict(exif)), 0)

    def test_jpeg_gps_and_comment_stripped_via_sanitize_profile_image(self):
        content = _jpeg_with_gps_and_comment()
        sanitized = sanitize_profile_image(content)
        result = Image.open(BytesIO(sanitized.content))
        exif = result.getexif()
        self.assertEqual(len(dict(exif)), 0)

    def test_png_text_chunks_stripped(self):
        content = _png_with_text_chunks()
        sanitized = sanitize_public_image(content)
        result = Image.open(BytesIO(sanitized.content))
        self.assertEqual(dict(getattr(result, "text", {})), {})

    def test_exif_orientation_applied_then_stripped(self):
        # Orientation 6 = rotate 270 CW (i.e. the visual left-red-stripe
        # column ends up on a different edge once rotation is applied).
        content = _jpeg_with_orientation(6)
        original = Image.open(BytesIO(content))
        original_size = original.size

        sanitized = sanitize_public_image(content)
        result = Image.open(BytesIO(sanitized.content))

        # exif_transpose swaps width/height for a 90-degree rotation.
        self.assertEqual(result.size, (original_size[1], original_size[0]))
        self.assertNotIn(0x0112, result.getexif())  # orientation tag itself is gone

    def test_icc_profile_stripped_by_default(self):
        content = _jpeg_with_icc_profile()
        original_flag = settings.IMAGE_PRESERVE_ICC_PROFILE
        settings.IMAGE_PRESERVE_ICC_PROFILE = False
        try:
            sanitized = sanitize_public_image(content)
            result = Image.open(BytesIO(sanitized.content))
            self.assertIsNone(result.info.get("icc_profile"))
        finally:
            settings.IMAGE_PRESERVE_ICC_PROFILE = original_flag

    def test_icc_profile_preserved_when_explicitly_enabled(self):
        content = _jpeg_with_icc_profile()
        original_flag = settings.IMAGE_PRESERVE_ICC_PROFILE
        settings.IMAGE_PRESERVE_ICC_PROFILE = True
        try:
            sanitized = sanitize_public_image(content)
            result = Image.open(BytesIO(sanitized.content))
            self.assertIsNotNone(result.info.get("icc_profile"))
        finally:
            settings.IMAGE_PRESERVE_ICC_PROFILE = original_flag

    def test_malformed_jpeg_raises_400_not_500(self):
        with self.assertRaises(HTTPException) as ctx:
            sanitize_public_image(b"not a real image, just garbage bytes" * 4)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_malformed_jpeg_raises_400_for_profile_image_too(self):
        with self.assertRaises(HTTPException) as ctx:
            sanitize_profile_image(b"not a real image, just garbage bytes" * 4)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_avatar_transparency_flattening_still_works(self):
        img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        img.putpixel((0, 0), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        sanitized = sanitize_profile_image(buf.getvalue())
        result = Image.open(BytesIO(sanitized.content))
        self.assertEqual(result.format, "JPEG")
        self.assertEqual(result.mode, "RGB")


class AnimatedImageRejectionTests(unittest.TestCase):
    """Amendment item 3: rejection must be based on Pillow's own post-decode
    detection, not the client-declared Content-Type/filename — resistant to
    a renamed file or spoofed MIME type."""

    def test_animated_gif_rejected_even_when_declared_as_jpeg(self):
        content = _animated_gif()
        with self.assertRaises(HTTPException) as ctx:
            sanitize_public_image(content, detected_content_type="image/jpeg")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_animated_webp_rejected_even_when_declared_as_png(self):
        content = _animated_webp()
        with self.assertRaises(HTTPException) as ctx:
            sanitize_public_image(content, detected_content_type="image/png")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_static_gif_is_unsupported_format_not_animated(self):
        # GIF is not in the allowed public-image format set at all (item B:
        # GIF rejected outright for posts/feedback) — even a static one.
        content = _static_gif()
        with self.assertRaises(HTTPException):
            sanitize_public_image(content)

    def test_static_webp_is_accepted(self):
        content = _static_webp()
        sanitized = sanitize_public_image(content)
        self.assertEqual(sanitized.content_type, "image/webp")

    def test_static_png_is_accepted(self):
        content = _static_png()
        sanitized = sanitize_public_image(content)
        self.assertEqual(sanitized.content_type, "image/png")

    def test_static_jpeg_is_accepted(self):
        content = _static_jpeg()
        sanitized = sanitize_public_image(content)
        self.assertEqual(sanitized.content_type, "image/jpeg")

    def test_reject_if_animated_or_unsupported_direct(self):
        with Image.open(BytesIO(_static_jpeg())) as img:
            reject_if_animated_or_unsupported(img)  # must not raise

        with Image.open(BytesIO(_animated_gif())) as img:
            with self.assertRaises(HTTPException):
                reject_if_animated_or_unsupported(img)


if __name__ == "__main__":
    unittest.main()
