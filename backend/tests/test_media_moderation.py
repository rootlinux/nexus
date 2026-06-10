import os
import secrets
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.models.moderation_signal import ModerationDetectionStatus, ModerationSurface
from app.services.moderation_intake import assess_media_input, assess_media_url


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "uploads"
VALID_PNG = (FIXTURES_DIR / "e2e-post-b.png").read_bytes()


class MediaModerationTests(unittest.TestCase):
    def test_clean_png_upload_is_allowed(self):
        assessment = assess_media_input(
            ModerationSurface.POST_MEDIA,
            content_type="image/png",
            original_filename="clean.png",
            content=VALID_PNG,
            content_size=len(VALID_PNG),
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.CLEAN)
        self.assertEqual(assessment.canonical_content_type, "image/png")

    def test_malformed_disguised_image_is_blocked(self):
        bogus = b"this is not an image"
        assessment = assess_media_input(
            ModerationSurface.POST_MEDIA,
            content_type="image/png",
            original_filename="bogus.png",
            content=bogus,
            content_size=len(bogus),
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("invalid_image_signature", assessment.reason_codes)

    def test_extension_and_mime_mismatch_is_blocked(self):
        assessment = assess_media_input(
            ModerationSurface.POST_MEDIA,
            content_type="image/jpeg",
            original_filename="mismatch.png",
            content=VALID_PNG,
            content_size=len(VALID_PNG),
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("mime_mismatch", assessment.reason_codes)

    def test_suspicious_filename_requires_review(self):
        assessment = assess_media_input(
            ModerationSurface.PROFILE_AVATAR,
            content_type="image/png",
            original_filename="nsfw-avatar.png",
            content=VALID_PNG,
            content_size=len(VALID_PNG),
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.SUSPICIOUS)
        self.assertTrue(assessment.requires_review)
        self.assertIn("suspicious_filename", assessment.reason_codes)

    def test_oversized_upload_is_blocked(self):
        assessment = assess_media_input(
            ModerationSurface.PROFILE_COVER,
            content_type="image/png",
            original_filename="huge.png",
            content=VALID_PNG,
            content_size=(8 * 1024 * 1024) + 1,
            max_size=8 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("file_too_large", assessment.reason_codes)

    def test_untrusted_media_url_is_blocked(self):
        assessment = assess_media_url(ModerationSurface.POST_MEDIA, "https://evil.example.com/payload.png")

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("external_media_url_not_allowed", assessment.reason_codes)


if __name__ == "__main__":
    unittest.main()
