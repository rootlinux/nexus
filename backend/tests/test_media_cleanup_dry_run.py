import os
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.media_asset import MediaAsset, MediaAssetStatus, MediaAssetType
from app.models.user_media_quota import UserMediaQuota
from app.scripts.media_cleanup_dry_run import _find_untracked_legacy_files
from app.services.media_assets import find_cleanup_candidates
from tests.media_test_support import create_test_user


class MediaCleanupDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.session_factory()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_expired_pending_asset_appears_fresh_one_does_not(self):
        user = await create_test_user(self.db)
        await self.db.flush()

        now = datetime.now(timezone.utc)
        expired = MediaAsset(
            owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE, storage_key=f"expired-{secrets.token_hex(4)}.jpg",
            content_type="image/jpeg", file_size_bytes=10, status=MediaAssetStatus.PENDING,
            created_at=now - timedelta(hours=settings.MEDIA_PENDING_EXPIRATION_HOURS + 1),
        )
        fresh = MediaAsset(
            owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE, storage_key=f"fresh-{secrets.token_hex(4)}.jpg",
            content_type="image/jpeg", file_size_bytes=10, status=MediaAssetStatus.PENDING,
            created_at=now,
        )
        self.db.add_all([expired, fresh])
        await self.db.commit()

        report = await find_cleanup_candidates(self.db, now=now)
        expired_keys = {item.storage_key for item in report.expired_pending}
        self.assertIn(expired.storage_key, expired_keys)
        self.assertNotIn(fresh.storage_key, expired_keys)

    async def test_deletion_pending_asset_appears_in_orphaned_bucket(self):
        user = await create_test_user(self.db)
        await self.db.flush()

        asset = MediaAsset(
            owner_user_id=user.id, media_type=MediaAssetType.AVATAR, storage_key=f"deleted-{secrets.token_hex(4)}.jpg",
            content_type="image/jpeg", file_size_bytes=10, status=MediaAssetStatus.DELETION_PENDING,
            deleted_at=datetime.now(timezone.utc),
        )
        self.db.add(asset)
        await self.db.commit()

        report = await find_cleanup_candidates(self.db)
        orphaned_keys = {item.storage_key for item in report.orphaned_deletion_pending}
        self.assertIn(asset.storage_key, orphaned_keys)

    async def test_report_is_idempotent_across_repeated_runs(self):
        user = await create_test_user(self.db)
        await self.db.flush()
        asset = MediaAsset(
            owner_user_id=user.id, media_type=MediaAssetType.AVATAR, storage_key=f"idem-{secrets.token_hex(4)}.jpg",
            content_type="image/jpeg", file_size_bytes=10, status=MediaAssetStatus.DELETION_PENDING,
            deleted_at=datetime.now(timezone.utc),
        )
        self.db.add(asset)
        await self.db.commit()

        report1 = await find_cleanup_candidates(self.db)
        report2 = await find_cleanup_candidates(self.db)
        self.assertEqual(
            {item.storage_key for item in report1.orphaned_deletion_pending},
            {item.storage_key for item in report2.orphaned_deletion_pending},
        )

    async def test_users_over_lifetime_limits_bucket(self):
        user_over = await create_test_user(self.db)
        user_under = await create_test_user(self.db)
        await self.db.flush()

        self.db.add_all([
            UserMediaQuota(
                user_id=user_over.id,
                file_count=settings.MEDIA_MAX_FILES_PER_USER + 1,
                total_bytes=0, daily_bytes=0, daily_window_started_at=datetime.now(timezone.utc),
            ),
            UserMediaQuota(
                user_id=user_under.id,
                file_count=1, total_bytes=100, daily_bytes=0, daily_window_started_at=datetime.now(timezone.utc),
            ),
        ])
        await self.db.commit()

        report = await find_cleanup_candidates(self.db)
        over_ids = {item.user_id for item in report.users_over_lifetime_limits}
        self.assertIn(user_over.id, over_ids)
        self.assertNotIn(user_under.id, over_ids)

    async def test_untracked_legacy_files_and_rows_dont_crash_and_are_labeled_separately(self):
        user = await create_test_user(self.db)
        await self.db.flush()

        missing_key = f"missing-on-disk-{secrets.token_hex(4)}.jpg"
        untracked_name = f"legacy-untracked-{secrets.token_hex(4)}.jpg"

        with tempfile.TemporaryDirectory() as uploads_dir, tempfile.TemporaryDirectory() as feedback_dir:
            # A tracked asset whose file does NOT exist on disk (db-row-without-file).
            missing_file_asset = MediaAsset(
                owner_user_id=user.id, media_type=MediaAssetType.AVATAR,
                storage_key=missing_key, content_type="image/jpeg",
                file_size_bytes=10, status=MediaAssetStatus.ATTACHED,
            )
            self.db.add(missing_file_asset)
            await self.db.commit()

            # An untracked file on disk with no MediaAsset row (file-without-db-row).
            (Path(uploads_dir) / untracked_name).write_bytes(b"legacy content")

            with patch.object(settings, "LOCAL_UPLOAD_DIR", uploads_dir), \
                 patch.object(settings, "FEEDBACK_ATTACHMENT_LOCAL_DIR", feedback_dir):
                result = await _find_untracked_legacy_files(self.db)

            self.assertTrue(any(untracked_name in f for f in result["files_without_db_row"]))
            self.assertIn(missing_key, result["db_rows_without_file"])


if __name__ == "__main__":
    unittest.main()
