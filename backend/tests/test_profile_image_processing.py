import os
import secrets
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nexus")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from fastapi import UploadFile
from PIL import Image
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.routes.users import (
    upload_my_avatar,
    upload_my_cover,
)
from app.core.config import settings
from app.services.image_processing import sanitize_profile_image
from app.models.moderation_signal import ModerationSurface
from tests.media_test_support import create_test_user


class _FakeStorageProvider:
    """Patched at BOTH resolution points the route now goes through:
    app.api.routes.users.get_storage_provider (used directly for
    get_public_url) and app.services.media_assets.get_storage_provider
    (the internal default write_media_to_storage_and_flush/
    run_media_operation fall back to when no explicit provider is passed).
    Patching only the former would let the real default LocalStorageProvider
    write to backend/uploads/ before the compensating delete on failure."""
    def __init__(self, public_url: str):
        self.public_url = public_url
        self.calls: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self._counter = 0

    async def save_file(self, *, content: bytes, content_type: str, original_filename: str | None = None):
        self._counter += 1
        self.calls.append(
            {
                "content": content,
                "content_type": content_type,
                "original_filename": original_filename,
            }
        )
        # Real commits now land in the persistent disposable-container DB, so a
        # fixed/counter-only key collides with rows left by other test runs
        # (UNIQUE constraint on storage_key) — suffix with a random token,
        # matching the pattern used by the other Task 3 test fixtures.
        key = f"normalized-upload-{self._counter}-{secrets.token_hex(4)}.jpg"
        return SimpleNamespace(storage_key=key, public_url=self.public_url)

    async def delete_file(self, *, storage_key: str) -> None:
        self.deleted.append(storage_key)

    def get_public_url(self, storage_key: str) -> str:
        return self.public_url


def _make_transparent_png() -> bytes:
    image = Image.new("RGBA", (2, 3), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 128))
    exif = Image.Exif()
    exif[274] = 6

    buffer = BytesIO()
    image.save(buffer, format="PNG", exif=exif)
    return buffer.getvalue()


def _make_upload_file(filename: str = "cover.png") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(_make_transparent_png()), headers={"content-type": "image/png"})


class ProfileImageProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    def test_normalize_profile_image_upload_flattens_transparency_and_applies_exif_orientation(self):
        sanitized = sanitize_profile_image(_make_transparent_png())
        self.assertEqual(sanitized.content_type, "image/jpeg")

        result = Image.open(BytesIO(sanitized.content))

        self.assertEqual(result.format, "JPEG")
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (3, 2))

        background = result.getpixel((0, 0))
        self.assertTrue(abs(background[0] - 13) <= 5)
        self.assertTrue(abs(background[1] - 14) <= 5)
        self.assertTrue(abs(background[2] - 18) <= 5)

        foreground = result.getpixel((2, 0))
        self.assertGreater(foreground[0], background[0] + 50)

    async def test_avatar_upload_saves_normalized_jpeg_and_keeps_response_shape(self):
        await self._assert_profile_endpoint_saves_jpeg(
            endpoint=upload_my_avatar,
            surface=ModerationSurface.PROFILE_AVATAR,
            response_field="avatar_url",
            user_field="avatar_url",
        )

    async def test_cover_upload_saves_normalized_jpeg_and_keeps_response_shape(self):
        await self._assert_profile_endpoint_saves_jpeg(
            endpoint=upload_my_cover,
            surface=ModerationSurface.PROFILE_COVER,
            response_field="cover_url",
            user_field="cover_url",
        )

    async def _assert_profile_endpoint_saves_jpeg(self, *, endpoint, surface, response_field: str, user_field: str):
        db = self.session_factory()
        try:
            current_user = await create_test_user(db)
            await db.commit()
            await db.refresh(current_user)

            storage = _FakeStorageProvider(public_url="http://localhost/uploads/normalized-upload.jpg")
            assessment = SimpleNamespace(
                is_blocked=False,
                requires_review=False,
                surface_type=surface,
                canonical_content_type="image/png",
            )
            signal = SimpleNamespace(media_url=None)

            with patch("app.api.routes.users.enforce_rate_limits", new=AsyncMock()), patch(
                "app.api.routes.users.assess_media_input",
                return_value=assessment,
            ) as assess_mock, patch(
                "app.api.routes.users.create_moderation_signal",
                new=AsyncMock(return_value=signal),
            ), patch(
                "app.api.routes.users.get_storage_provider",
                return_value=storage,
            ), patch(
                "app.services.media_assets.get_storage_provider",
                return_value=storage,
            ):
                response = await endpoint(
                    request=SimpleNamespace(headers={}),
                    file=_make_upload_file(),
                    current_user=current_user,
                    db=db,
                )

            assess_mock.assert_called_once()
            self.assertEqual(storage.calls[0]["content_type"], "image/jpeg")
            self.assertEqual(storage.calls[0]["original_filename"], "cover.png")

            saved_image = Image.open(BytesIO(storage.calls[0]["content"]))
            self.assertEqual(saved_image.format, "JPEG")

            self.assertEqual(getattr(response, response_field), storage.public_url)
            self.assertEqual(getattr(current_user, user_field), storage.public_url)
            self.assertEqual(signal.media_url, storage.public_url)
        finally:
            await db.close()


if __name__ == "__main__":
    unittest.main()
