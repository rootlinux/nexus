import os
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.services.feedback_retention import delete_feedback_attachments, find_stale_feedback_attachments


class FeedbackRetentionTests(unittest.TestCase):
    def test_find_stale_feedback_attachments_uses_retention_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stale = root / "stale.png"
            fresh = root / "fresh.png"
            stale.write_bytes(b"old")
            fresh.write_bytes(b"new")

            now = datetime(2026, 4, 11, tzinfo=timezone.utc)
            stale_mtime = (now - timedelta(days=45)).timestamp()
            fresh_mtime = (now - timedelta(days=5)).timestamp()
            os.utime(stale, (stale_mtime, stale_mtime))
            os.utime(fresh, (fresh_mtime, fresh_mtime))

            items = find_stale_feedback_attachments(root, retention_days=30, now=now)

        self.assertEqual([item.path.name for item in items], ["stale.png"])
        self.assertEqual(items[0].size_bytes, 3)
        self.assertGreater(items[0].age_days, 40)

    def test_delete_feedback_attachments_removes_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "stale.png"
            target.write_bytes(b"old")

            items = find_stale_feedback_attachments(
                root,
                retention_days=1,
                now=datetime.now(timezone.utc) + timedelta(days=2),
            )
            deleted = delete_feedback_attachments(items)

            self.assertEqual(deleted, 1)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
