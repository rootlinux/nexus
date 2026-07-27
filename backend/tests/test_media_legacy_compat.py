import os
import secrets
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.post import Post
from app.services.media_assets import attach_pending_media, mark_media_deleted_for_posts, mark_media_superseded
from app.services.post_views import delete_post_closure
from tests.media_test_support import create_test_user


class _FakeStorageProvider:
    def __init__(self):
        self.delete_calls: list[str] = []

    async def delete_file(self, *, storage_key: str) -> None:
        self.delete_calls.append(storage_key)


class MediaLegacyCompatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.session_factory()
        self.storage = _FakeStorageProvider()
        self.patcher = patch("app.services.media_assets.get_storage_provider", return_value=self.storage)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.db.close()
        await self.engine.dispose()

    async def test_avatar_replacement_with_no_tracked_row_is_a_safe_noop(self):
        # A legacy avatar_url with no MediaAsset row at all (predates this feature).
        await mark_media_superseded(self.db, storage_key="legacy-avatar-key.jpg")  # must not raise
        await self.db.commit()
        self.assertEqual(self.storage.delete_calls, [])  # dry-run boundary holds even for legacy-compat paths

    async def test_post_deletion_with_legacy_media_url_and_no_row_succeeds(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        post = Post(user_id=user.id, content="legacy post", media_url="/uploads/legacy-file.jpg")
        self.db.add(post)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(post)

        # Must succeed (post is deletable) even though media_url has no MediaAsset row.
        await delete_post_closure(self.db, post, actor_user_id=user.id, reason="test")
        await self.db.commit()
        self.assertEqual(self.storage.delete_calls, [])

    async def test_direct_mark_media_deleted_for_posts_with_no_tracked_rows_is_safe(self):
        count = await mark_media_deleted_for_posts(self.db, post_ids=[999999, 999998])
        self.assertEqual(count, 0)
        await self.db.commit()

    async def test_post_create_referencing_untracked_legacy_key_is_still_blocked(self):
        # Corrected assertion (fourth amendment): unlike the legacy-tolerant supersede/
        # delete paths above, attaching an untracked key to NEWLY CREATED content is
        # never allowed — there is no untracked-media bypass for new post creation.
        user = await create_test_user(self.db)
        await self.db.commit()

        post = Post(user_id=user.id, content="new post referencing an untracked key")
        self.db.add(post)
        await self.db.flush()

        with self.assertRaises(HTTPException) as ctx:
            await attach_pending_media(
                self.db, storage_key="untracked-legacy-key.jpg", owner_user_id=user.id,
                attached_to_type="post", attached_to_id=post.id,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        await self.db.rollback()
        self.assertEqual(self.storage.delete_calls, [])


if __name__ == "__main__":
    unittest.main()
