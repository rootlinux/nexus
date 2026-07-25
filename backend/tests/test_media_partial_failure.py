import logging
import os
import secrets
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.media_asset import MediaAsset, MediaAssetType
from app.models.post import Post
from app.services.media_assets import (
    attach_pending_media,
    run_media_operation,
    write_media_to_storage_and_flush,
)
from tests.media_test_support import create_test_user


class _FakeStorageProvider:
    def __init__(self):
        self._counter = 0
        self.deleted: list[str] = []

    async def save_file(self, *, content: bytes, content_type: str, original_filename=None):
        self._counter += 1
        key = f"partial-{self._counter}-{secrets.token_hex(4)}.jpg"
        return type("StoredMedia", (), {"storage_key": key, "public_url": f"/uploads/{key}"})()

    async def delete_file(self, *, storage_key: str) -> None:
        self.deleted.append(storage_key)


class MediaPartialFailureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.session_factory()
        self.storage = _FakeStorageProvider()
        self.user = await create_test_user(self.db)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _fresh_session(self):
        return self.session_factory()

    async def test_failure_after_registration_rolls_back_and_compensates(self):
        # DEFINITE failure: fn raises right after write_media_to_storage_and_flush
        # registers the PENDING row but before anything else succeeds. Nothing
        # was committed, so this must roll back and compensating-delete the
        # just-written file.
        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=self.user.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg", storage_provider=self.storage,
            )
            compensation.append(asset.storage_key)
            raise RuntimeError("simulated failure after registration")

        with self.assertRaises(RuntimeError):
            await run_media_operation(self.db, _op, storage_provider=self.storage)

        self.assertEqual(len(self.storage.deleted), 1)
        deleted_key = self.storage.deleted[0]

        check_db = await self._fresh_session()
        row = await check_db.scalar(select(MediaAsset).where(MediaAsset.storage_key == deleted_key))
        self.assertIsNone(row)  # rollback undid the registration entirely
        await check_db.close()

    async def test_failure_after_attachment_rolls_back_and_compensates(self):
        # DEFINITE failure: registration AND attachment both succeed
        # (pre-commit), then a later step in the same operation raises —
        # e.g. a subsequent unrelated write failing. Must still roll back
        # and compensate, since nothing has committed yet.
        post = Post(user_id=self.user.id, content="pending post")
        self.db.add(post)
        await self.db.flush()
        post_id = post.id

        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=self.user.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg", storage_provider=self.storage,
            )
            compensation.append(asset.storage_key)
            await attach_pending_media(
                self.db, storage_key=asset.storage_key, owner_user_id=self.user.id,
                attached_to_type="post", attached_to_id=post_id,
            )
            raise RuntimeError("simulated failure after attachment")

        with self.assertRaises(RuntimeError):
            await run_media_operation(self.db, _op, storage_provider=self.storage)

        self.assertEqual(len(self.storage.deleted), 1)
        deleted_key = self.storage.deleted[0]

        check_db = await self._fresh_session()
        row = await check_db.scalar(select(MediaAsset).where(MediaAsset.storage_key == deleted_key))
        self.assertIsNone(row)  # rollback undid both registration and attachment
        post_row = await check_db.scalar(select(Post).where(Post.id == post_id))
        self.assertIsNone(post_row)  # the flushed-but-uncommitted post is gone too
        await check_db.close()

    async def test_commit_failure_logs_unknown_outcome_and_never_deletes(self):
        # INDETERMINATE outcome: fn succeeds fully, but db.commit() itself
        # raises (simulating e.g. a dropped connection after COMMIT was sent
        # but before the acknowledgment came back). This must NOT be treated
        # as a proven failure — no compensating delete may be attempted,
        # since the row could have actually landed. Must log
        # media_commit_outcome_unknown for a future reconciliation pass.
        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=self.user.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg", storage_provider=self.storage,
            )
            compensation.append(asset.storage_key)
            return asset

        with patch.object(self.db, "commit", AsyncMock(side_effect=RuntimeError("connection dropped"))):
            with self.assertLogs("app.services.media_assets", level="ERROR") as log_ctx:
                with self.assertRaises(RuntimeError):
                    await run_media_operation(self.db, _op, storage_provider=self.storage)

        self.assertTrue(any("media_commit_outcome_unknown" in msg for msg in log_ctx.output))
        self.assertEqual(self.storage.deleted, [])  # never compensate on an indeterminate commit outcome


if __name__ == "__main__":
    unittest.main()
