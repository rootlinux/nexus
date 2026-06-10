import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://placeholder")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.models.moderation_signal import ModerationDetectionStatus, ModerationSurface
from app.models.post import Post
from app.models.moderation_signal import ModerationSignal
from app.services.moderation_intake import assess_media_input, assess_media_url, assess_text_content


class ModerationServiceTests(unittest.TestCase):
    def test_r2_post_and_moderation_timestamp_columns_are_timezone_aware(self):
        self.assertTrue(Post.__table__.c.created_at.type.timezone)
        self.assertTrue(Post.__table__.c.moderated_at.type.timezone)
        self.assertTrue(ModerationSignal.__table__.c.created_at.type.timezone)
        self.assertTrue(ModerationSignal.__table__.c.resolved_at.type.timezone)

    def test_blocks_obvious_spam_phrase(self):
        assessment = assess_text_content(
            ModerationSurface.POST_TEXT,
            "Claim your free money crypto giveaway now",
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("spam_scam", assessment.reason_codes)

    def test_marks_suspicious_profile_text(self):
        assessment = assess_text_content(
            ModerationSurface.PROFILE_BIO,
            "DM me on telegram for promo code access",
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.SUSPICIOUS)
        self.assertIn("spam_terms", assessment.reason_codes)

    def test_clean_text_stays_clean(self):
        assessment = assess_text_content(
            ModerationSurface.DM_TEXT,
            "Want to grab coffee after work tomorrow?",
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.CLEAN)
        self.assertEqual(assessment.reason_codes, [])

    def test_blocks_unsafe_media_extension(self):
        assessment = assess_media_input(
            ModerationSurface.POST_MEDIA,
            content=b"stub",
            content_type="image/png",
            original_filename="payload.svg",
            content_size=1024,
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("unsafe_file_type", assessment.reason_codes)

    def test_flags_extension_mismatch_as_suspicious(self):
        assessment = assess_media_input(
            ModerationSurface.PROFILE_AVATAR,
            content=b"\x89PNG\r\n\x1a\navatar",
            content_type="image/png",
            original_filename="avatar.jpg",
            content_size=1024,
            max_size=5 * 1024 * 1024,
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("extension_mismatch", assessment.reason_codes)

    def test_blocks_non_http_media_scheme(self):
        assessment = assess_media_url(
            ModerationSurface.POST_MEDIA,
            "javascript:alert(1)",
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("unsupported_media_scheme", assessment.reason_codes)

    def test_blocks_protocol_relative_media_url(self):
        assessment = assess_media_url(
            ModerationSurface.POST_MEDIA,
            "//evil.example/payload.png",
        )

        self.assertEqual(assessment.detection_status, ModerationDetectionStatus.BLOCKED)
        self.assertIn("protocol_relative_media_url", assessment.reason_codes)


if __name__ == "__main__":
    unittest.main()
