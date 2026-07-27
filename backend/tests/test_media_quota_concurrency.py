import asyncio
import os
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.media_asset import MediaAsset, MediaAssetStatus, MediaAssetType
from app.models.post import Post
from app.models.user_media_quota import UserMediaQuota
from app.services.media_assets import (
    mark_media_deleted_for_posts,
    mark_media_superseded,
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
        key = f"conc-{self._counter}-{secrets.token_hex(4)}.jpg"
        return type("StoredMedia", (), {"storage_key": key, "public_url": f"/uploads/{key}"})()

    async def delete_file(self, *, storage_key: str) -> None:
        self.deleted.append(storage_key)


class MediaQuotaConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        setup_db = self.session_factory()
        self.user = await create_test_user(setup_db)
        await setup_db.commit()
        await setup_db.close()

        self._orig_daily = settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER
        self._orig_files = settings.MEDIA_MAX_FILES_PER_USER

    async def asyncTearDown(self):
        settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER = self._orig_daily
        settings.MEDIA_MAX_FILES_PER_USER = self._orig_files
        await self.engine.dispose()

    async def _upload_once(self, storage, size_bytes: int) -> str | None:
        """Returns None on success, the HTTP status code on failure. Uses its
        own dedicated DB session, as required for real concurrent access."""
        db = self.session_factory()
        with patch("app.services.media_assets.get_storage_provider", return_value=storage):
            async def _op(compensation):
                asset = await write_media_to_storage_and_flush(
                    db, owner_user_id=self.user.id, media_type=MediaAssetType.POST_IMAGE,
                    content=b"x" * size_bytes, content_type="image/jpeg",
                )
                compensation.append(asset.storage_key)
                return asset

            try:
                await run_media_operation(db, _op)
                return None
            except HTTPException as exc:
                return exc.status_code
            finally:
                await db.close()

    async def test_concurrent_uploads_enforce_daily_limit(self):
        settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER = 300  # tight: exactly 3 uploads of 100 bytes fit
        storage = _FakeStorageProvider()

        results = await asyncio.gather(*[self._upload_once(storage, 100) for _ in range(5)])
        successes = [r for r in results if r is None]
        failures = [r for r in results if r == 429]
        self.assertEqual(len(successes), 3)
        self.assertEqual(len(failures), 2)

        check_db = self.session_factory()
        quota = await check_db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == self.user.id))
        self.assertLessEqual(quota.daily_bytes, settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER)
        await check_db.close()

    async def test_concurrent_logical_deletion_of_same_asset_never_changes_quota(self):
        storage = _FakeStorageProvider()
        setup_db = self.session_factory()
        with patch("app.services.media_assets.get_storage_provider", return_value=storage):
            async def _op(compensation):
                asset = await write_media_to_storage_and_flush(
                    setup_db, owner_user_id=self.user.id, media_type=MediaAssetType.AVATAR,
                    content=b"x" * 50, content_type="image/jpeg",
                )
                compensation.append(asset.storage_key)
                return asset

            asset = await run_media_operation(setup_db, _op)
        await setup_db.close()

        before_check_db = self.session_factory()
        before = await before_check_db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == self.user.id))
        before_values = (before.file_count, before.total_bytes, before.daily_bytes)
        await before_check_db.close()

        async def _supersede_once():
            db = self.session_factory()
            try:
                await mark_media_superseded(db, storage_key=asset.storage_key)
                await db.commit()
            finally:
                await db.close()

        await asyncio.gather(*[_supersede_once() for _ in range(5)])

        after_check_db = self.session_factory()
        after = await after_check_db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == self.user.id))
        self.assertEqual((after.file_count, after.total_bytes, after.daily_bytes), before_values)
        deleted_asset = await after_check_db.scalar(select(MediaAsset).where(MediaAsset.storage_key == asset.storage_key))
        self.assertEqual(deleted_asset.status, MediaAssetStatus.DELETION_PENDING)
        await after_check_db.close()

    async def test_repeated_logical_deletion_does_not_restore_daily_capacity(self):
        settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER = 100
        storage = _FakeStorageProvider()

        # Max out the daily allowance.
        status_code = await self._upload_once(storage, 100)
        self.assertIsNone(status_code)

        # Logically delete it.
        list_db = self.session_factory()
        asset = await list_db.scalar(
            select(MediaAsset).where(MediaAsset.owner_user_id == self.user.id).order_by(MediaAsset.id.desc())
        )
        await mark_media_superseded(list_db, storage_key=asset.storage_key)
        await list_db.commit()
        await list_db.close()

        # Attempting another upload today must still fail — capacity was not restored.
        second_status = await self._upload_once(storage, 100)
        self.assertEqual(second_status, 429)

    async def test_mixed_concurrent_upload_and_delete_consistency(self):
        storage = _FakeStorageProvider()

        async def _upload_and_maybe_delete(should_delete: bool):
            db = self.session_factory()
            try:
                async def _op(compensation):
                    asset = await write_media_to_storage_and_flush(
                        db, owner_user_id=self.user.id, media_type=MediaAssetType.POST_IMAGE,
                        content=b"y" * 10, content_type="image/jpeg",
                    )
                    compensation.append(asset.storage_key)
                    return asset

                with patch("app.services.media_assets.get_storage_provider", return_value=storage):
                    asset = await run_media_operation(db, _op)
                if should_delete:
                    await mark_media_superseded(db, storage_key=asset.storage_key)
                    await db.commit()
            finally:
                await db.close()

        await asyncio.gather(*[_upload_and_maybe_delete(i % 2 == 0) for i in range(6)])

        check_db = self.session_factory()
        quota = await check_db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == self.user.id))
        all_assets = (await check_db.scalars(
            select(MediaAsset).where(MediaAsset.owner_user_id == self.user.id)
        )).all()
        # Corrected invariant: quota reflects EVERY ever-registered asset, regardless
        # of logical deletion status — logical deletion never removes a row's
        # contribution to quota (physical bytes remain on disk).
        self.assertEqual(quota.file_count, len(all_assets))
        self.assertEqual(quota.total_bytes, sum(a.file_size_bytes for a in all_assets))
        await check_db.close()

    async def test_lock_ordering_deadlock_freedom(self):
        user_a = self.user
        setup_db = self.session_factory()
        user_b = await create_test_user(setup_db)
        await setup_db.commit()
        await setup_db.close()

        storage = _FakeStorageProvider()

        async def _upload_for(user):
            db = self.session_factory()
            try:
                async def _op(compensation):
                    asset = await write_media_to_storage_and_flush(
                        db, owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE,
                        content=b"z" * 5, content_type="image/jpeg",
                    )
                    compensation.append(asset.storage_key)
                    return asset

                with patch("app.services.media_assets.get_storage_provider", return_value=storage):
                    return await run_media_operation(db, _op)
            finally:
                await db.close()

        # Seed a few tracked posts/assets for both users, in interleaved order.
        assets_a = [await _upload_for(user_a) for _ in range(2)]
        assets_b = [await _upload_for(user_b) for _ in range(2)]

        seed_db = self.session_factory()
        post_a = Post(user_id=user_a.id, content="a", media_url=f"/uploads/{assets_a[0].storage_key}")
        post_b = Post(user_id=user_b.id, content="b", media_url=f"/uploads/{assets_b[0].storage_key}")
        seed_db.add_all([post_a, post_b])
        await seed_db.flush()
        from app.services.media_assets import attach_pending_media
        await attach_pending_media(seed_db, storage_key=assets_a[0].storage_key, owner_user_id=user_a.id, attached_to_type="post", attached_to_id=post_a.id)
        await attach_pending_media(seed_db, storage_key=assets_b[0].storage_key, owner_user_id=user_b.id, attached_to_type="post", attached_to_id=post_b.id)
        await seed_db.commit()
        post_a_id, post_b_id = post_a.id, post_b.id
        await seed_db.close()

        async def _reserve_for(user):
            db = self.session_factory()
            try:
                async def _op(compensation):
                    asset = await write_media_to_storage_and_flush(
                        db, owner_user_id=user.id, media_type=MediaAssetType.POST_IMAGE,
                        content=b"w" * 5, content_type="image/jpeg",
                    )
                    compensation.append(asset.storage_key)
                    return asset

                with patch("app.services.media_assets.get_storage_provider", return_value=storage):
                    await run_media_operation(db, _op)
            finally:
                await db.close()

        async def _delete_for(post_ids):
            # Each closure commits its OWN session as soon as its own work
            # finishes, exactly like two independent real HTTP requests would.
            # Gathering both calls and committing only after BOTH resolve (the
            # original shape here) creates an application-level circular wait
            # that Postgres's deadlock detector cannot see (each backend is
            # merely idle-in-transaction waiting on its own client, not on the
            # other backend) — confirmed via pg_locks/pg_stat_activity during
            # the hang, not an actual lock-ordering bug in the production code.
            db = self.session_factory()
            try:
                await mark_media_deleted_for_posts(db, post_ids=post_ids)
                await db.commit()
            finally:
                await db.close()

        async def _delete_closure(post_ids_ab, post_ids_ba):
            await asyncio.gather(_delete_for(post_ids_ab), _delete_for(post_ids_ba))

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _reserve_for(user_a),
                    _reserve_for(user_b),
                    _delete_closure([post_a_id, post_b_id], [post_b_id, post_a_id]),
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            self.fail("concurrent quota reservation + deletion deadlocked (exceeded 10s timeout)")

        check_db = self.session_factory()
        for user in (user_a, user_b):
            quota = await check_db.scalar(select(UserMediaQuota).where(UserMediaQuota.user_id == user.id))
            self.assertGreaterEqual(quota.file_count, 0)
            self.assertGreaterEqual(quota.total_bytes, 0)
        await check_db.close()


if __name__ == "__main__":
    unittest.main()
