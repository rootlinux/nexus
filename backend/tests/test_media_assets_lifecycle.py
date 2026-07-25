import os
import secrets
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.media_asset import MediaAsset, MediaAssetStatus, MediaAssetType
from app.models.post import Post
from app.services.media_assets import (
    attach_pending_media,
    mark_media_deleted_for_posts,
    mark_media_superseded,
    run_media_operation,
    write_media_to_storage_and_flush,
)
from app.services.post_views import delete_post_closure
from tests.media_test_support import create_test_user


class _FakeStorageProvider:
    def __init__(self):
        self.save_calls: list[dict] = []
        self.delete_calls: list[str] = []
        self._counter = 0

    async def save_file(self, *, content: bytes, content_type: str, original_filename=None):
        self._counter += 1
        key = f"fake-{self._counter}-{secrets.token_hex(4)}.jpg"
        self.save_calls.append({"content": content, "content_type": content_type, "storage_key": key})
        return type("StoredMedia", (), {"storage_key": key, "public_url": f"/uploads/{key}"})()

    def get_public_url(self, storage_key: str) -> str:
        return f"/uploads/{storage_key}"

    async def delete_file(self, *, storage_key: str) -> None:
        self.delete_calls.append(storage_key)


class MediaAssetsLifecycleTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_avatar_replacement_supersedes_old_asset_without_deleting_file(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        async def _op1(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=user.id, media_type=MediaAssetType.AVATAR,
                content=b"first", content_type="image/jpeg",
            )
            compensation.append(asset.storage_key)
            await attach_pending_media(
                self.db, storage_key=asset.storage_key, owner_user_id=user.id,
                attached_to_type="user_avatar", attached_to_id=user.id,
            )
            return asset.storage_key

        first_key = await run_media_operation(self.db, _op1)

        async def _op2(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=user.id, media_type=MediaAssetType.AVATAR,
                content=b"second", content_type="image/jpeg",
            )
            compensation.append(asset.storage_key)
            await attach_pending_media(
                self.db, storage_key=asset.storage_key, owner_user_id=user.id,
                attached_to_type="user_avatar", attached_to_id=user.id,
            )
            await mark_media_superseded(self.db, storage_key=first_key)
            return asset.storage_key

        await run_media_operation(self.db, _op2)

        old_asset = await self.db.scalar(select(MediaAsset).where(MediaAsset.storage_key == first_key))
        self.assertEqual(old_asset.status, MediaAssetStatus.DELETION_PENDING)
        self.assertEqual(self.storage.delete_calls, [])  # dry-run boundary: never physically deleted

    async def test_post_create_attaches_own_tracked_pending_asset(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg",
            )
            compensation.append(asset.storage_key)
            return asset.storage_key

        storage_key = await run_media_operation(self.db, _op)

        post = Post(user_id=user.id, content="hello", media_url=f"/uploads/{storage_key}")
        self.db.add(post)
        await self.db.flush()
        await attach_pending_media(
            self.db, storage_key=storage_key, owner_user_id=user.id,
            attached_to_type="post", attached_to_id=post.id,
        )
        await self.db.commit()

        asset = await self.db.scalar(select(MediaAsset).where(MediaAsset.storage_key == storage_key))
        self.assertEqual(asset.status, MediaAssetStatus.ATTACHED)
        self.assertEqual(asset.attached_to_type, "post")
        self.assertEqual(asset.attached_to_id, post.id)

    async def test_post_create_rejects_someone_elses_tracked_pending_key(self):
        owner = await create_test_user(self.db)
        other_user = await create_test_user(self.db)
        await self.db.commit()

        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=owner.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg",
            )
            compensation.append(asset.storage_key)
            return asset.storage_key

        storage_key = await run_media_operation(self.db, _op)

        post = Post(user_id=other_user.id, content="hello")
        self.db.add(post)
        await self.db.flush()

        with self.assertRaises(HTTPException) as ctx:
            await attach_pending_media(
                self.db, storage_key=storage_key, owner_user_id=other_user.id,
                attached_to_type="post", attached_to_id=post.id,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        await self.db.rollback()

    async def test_post_create_rejects_untracked_storage_key(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        post = Post(user_id=user.id, content="hello")
        self.db.add(post)
        await self.db.flush()

        with self.assertRaises(HTTPException) as ctx:
            await attach_pending_media(
                self.db, storage_key="never-uploaded.jpg", owner_user_id=user.id,
                attached_to_type="post", attached_to_id=post.id,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        await self.db.rollback()

    async def test_post_deletion_cascades_media_status_to_deletion_pending(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        async def _op(compensation):
            asset = await write_media_to_storage_and_flush(
                self.db, owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE,
                content=b"img", content_type="image/jpeg",
            )
            compensation.append(asset.storage_key)
            return asset.storage_key

        storage_key = await run_media_operation(self.db, _op)

        post = Post(user_id=user.id, content="hello", media_url=f"/uploads/{storage_key}")
        self.db.add(post)
        await self.db.flush()
        await attach_pending_media(
            self.db, storage_key=storage_key, owner_user_id=user.id,
            attached_to_type="post", attached_to_id=post.id,
        )
        await self.db.commit()
        await self.db.refresh(post)

        await delete_post_closure(self.db, post, actor_user_id=user.id, reason="test")
        await self.db.commit()

        asset = await self.db.scalar(select(MediaAsset).where(MediaAsset.storage_key == storage_key))
        self.assertEqual(asset.status, MediaAssetStatus.DELETION_PENDING)
        self.assertEqual(self.storage.delete_calls, [])  # dry-run boundary holds through post deletion too

    async def test_lifetime_limits_tracked_but_not_enforced(self):
        user = await create_test_user(self.db)
        await self.db.commit()

        original_max_files = settings.MEDIA_MAX_FILES_PER_USER
        settings.MEDIA_MAX_FILES_PER_USER = 1
        try:
            for _ in range(3):
                async def _op(compensation):
                    asset = await write_media_to_storage_and_flush(
                        self.db, owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE,
                        content=b"img", content_type="image/jpeg",
                    )
                    compensation.append(asset.storage_key)
                    return asset

                await run_media_operation(self.db, _op)  # must never raise despite exceeding the "limit"
        finally:
            settings.MEDIA_MAX_FILES_PER_USER = original_max_files

        from app.models.user_media_quota import UserMediaQuota
        quota = await self.db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == user.id))
        self.assertEqual(quota.file_count, 3)  # tracked accurately past the "limit," never blocked


if __name__ == "__main__":
    unittest.main()
