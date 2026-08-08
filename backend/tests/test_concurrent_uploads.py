import asyncio
import os
import secrets
import shutil
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import httpx
from fastapi import Depends
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api import deps
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.user import User
from tests.media_test_support import create_test_user

UPLOAD_COUNT = 20


def _make_png_bytes(marker: bytes = b"") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue() + marker


class ConcurrentUploadsTests(unittest.IsolatedAsyncioTestCase):
    """Fires many real avatar uploads through the actual FastAPI route
    concurrently, over a real disposable-Postgres-backed session per
    request, to verify Task 4's asyncio.to_thread offload actually keeps
    the event loop free under real concurrent load — not just at the
    isolated LocalStorageProvider unit level covered by
    test_storage_async_offload.py."""

    async def asyncSetUp(self):
        # Clear any overrides left behind by previously-run tests before
        # installing our own — without this the test inherits foreign
        # dependency overrides (e.g. require_admin_session from an earlier
        # admin test) and the upload route resolves wrong dependencies,
        # producing an intermittent non-201 response.
        app.dependency_overrides.clear()

        self.temp_upload_dir = tempfile.mkdtemp(prefix="concurrent-uploads-test-")
        self._original_upload_dir = settings.LOCAL_UPLOAD_DIR
        settings.LOCAL_UPLOAD_DIR = self.temp_upload_dir

        # NullPool: TestClient/AsyncClient-driven requests in this suite don't
        # guarantee one persistent connection-safe loop across separate
        # requests (see the Task 3 handoff entry) — a fresh physical
        # connection per checkout sidesteps that regardless.
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_session_factory = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_session_factory() as session:
                user = await create_test_user(session)
                await session.commit()
                self.user_id = user.id
        finally:
            await temp_engine.dispose()

        async def override_db():
            async with self.session_factory() as session:
                yield session

        async def override_user(db: AsyncSession = Depends(get_db)):
            # Depends(get_db) here resolves to the SAME per-request session as
            # the route's own `db` param (FastAPI caches dependency results
            # per callable per request) — required because upload_my_avatar
            # ends with `await db.refresh(current_user)`, which needs a real
            # mapped instance attached to that exact session, not a detached
            # stand-in object.
            return await db.get(User, self.user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[deps.get_current_interactive_user] = override_user

        assessment = SimpleNamespace(
            is_blocked=False, requires_review=False,
            surface_type=SimpleNamespace(value="profile_avatar"), canonical_content_type="image/png",
        )
        signal = SimpleNamespace(media_url=None)
        self._patches = [
            patch("app.api.routes.users.enforce_rate_limits", new=AsyncMock()),
            patch("app.api.routes.users.assess_media_input", return_value=assessment),
            patch("app.api.routes.users.create_moderation_signal", new=AsyncMock(return_value=signal)),
        ]
        for p in self._patches:
            p.start()

    async def asyncTearDown(self):
        for p in self._patches:
            p.stop()
        app.dependency_overrides.clear()
        settings.LOCAL_UPLOAD_DIR = self._original_upload_dir
        await self.engine.dispose()
        shutil.rmtree(self.temp_upload_dir, ignore_errors=True)

    async def _post_avatar(self, client: httpx.AsyncClient, marker: bytes = b"") -> httpx.Response:
        return await client.post(
            "/api/users/me/avatar",
            files={"file": ("avatar.png", _make_png_bytes(marker), "image/png")},
        )

    async def test_concurrent_avatar_uploads_all_succeed_with_distinct_storage_keys(self):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            start = time.monotonic()
            responses = await asyncio.gather(*[self._post_avatar(client) for _ in range(UPLOAD_COUNT)])
            elapsed = time.monotonic() - start

        statuses = [r.status_code for r in responses]
        self.assertEqual(statuses, [201] * UPLOAD_COUNT, responses[0].text if responses else "")
        avatar_urls = [r.json()["avatar_url"] for r in responses]
        self.assertEqual(len(set(avatar_urls)), UPLOAD_COUNT)  # every upload got its own storage key

        saved_files = list(Path(self.temp_upload_dir).iterdir())
        self.assertEqual(len(saved_files), UPLOAD_COUNT)
        # Generous sanity bound — real concurrency, not proof of a specific
        # speed, just that N uploads didn't take anywhere near N times as
        # long as one (which would indicate accidental serialization).
        self.assertLess(elapsed, 5.0)

    async def test_slow_disk_write_in_one_upload_does_not_block_others_or_health_check(self):
        real_write_bytes = Path.write_bytes
        slow_marker = b"__SLOW_UPLOAD_MARKER__"
        SLOW_WRITE_SECONDS = 0.6

        def _maybe_slow_write_bytes(self_path, data):
            if slow_marker in data:
                time.sleep(SLOW_WRITE_SECONDS)  # blocking sleep — simulates slow disk I/O
            return real_write_bytes(self_path, data)

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            with patch.object(Path, "write_bytes", _maybe_slow_write_bytes):
                start = time.monotonic()

                async def _timed_health_check():
                    await asyncio.sleep(0.05)  # let the batch actually start first
                    health_start = time.monotonic()
                    response = await client.get("/health")
                    return response, time.monotonic() - health_start

                uploads = [self._post_avatar(client, marker=slow_marker if i == 0 else b"") for i in range(UPLOAD_COUNT)]
                results = await asyncio.gather(*uploads, _timed_health_check())
                elapsed = time.monotonic() - start

        upload_responses = results[:UPLOAD_COUNT]
        health_response, health_elapsed = results[UPLOAD_COUNT]

        statuses = [r.status_code for r in upload_responses]
        self.assertEqual(statuses, [201] * UPLOAD_COUNT)

        self.assertEqual(health_response.status_code, 200)
        # The event loop itself was never blocked by the slow write (which
        # runs in a background thread) — a trivial concurrent request must
        # still complete almost immediately, not wait out the slow upload.
        self.assertLess(health_elapsed, SLOW_WRITE_SECONDS / 2)

        # Secondary sanity check only — the health-check-latency assertion
        # above is the real proof the event loop wasn't blocked. This bound
        # is deliberately generous (not a tight multiple of SLOW_WRITE_SECONDS):
        # 20 real Pillow encodes plus 2 real DB round trips each against the
        # disposable Postgres container carry enough of their own timing
        # variance under load that a tight bound here flaked independently of
        # whether offloading actually worked (observed directly: two
        # consecutive real runs finished in ~1.26s/~1.43s wall-clock — safely
        # short in absolute terms, but only ~0.05-0.24s over a 2x-multiplier
        # bound that was measuring incidental system variance, not a
        # serialization regression).
        self.assertLess(elapsed, SLOW_WRITE_SECONDS + 3.0)


if __name__ == "__main__":
    unittest.main()
