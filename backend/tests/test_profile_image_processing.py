import os
import secrets
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from fastapi import UploadFile
from PIL import Image

from app.api.routes.users import (
    _normalize_profile_image_upload,
    upload_my_avatar,
    upload_my_cover,
)
from app.models.moderation_signal import ModerationSurface


class _FakeStorageProvider:
    def __init__(self, public_url: str):
        self.public_url = public_url
        self.calls: list[dict[str, object]] = []

    async def save_file(self, *, content: bytes, content_type: str, original_filename: str | None = None):
        self.calls.append(
            {
                "content": content,
                "content_type": content_type,
                "original_filename": original_filename,
            }
        )
        return SimpleNamespace(storage_key="normalized-upload.jpg", public_url=self.public_url)


class _FakeDB:
    def __init__(self):
        self.commit = AsyncMock()
        self.refresh = AsyncMock()


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
    def test_normalize_profile_image_upload_flattens_transparency_and_applies_exif_orientation(self):
        normalized = _normalize_profile_image_upload(_make_transparent_png())

        result = Image.open(BytesIO(normalized))

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
        storage = _FakeStorageProvider(public_url="http://localhost/uploads/normalized-upload.jpg")
        db = _FakeDB()
        current_user = SimpleNamespace(id=7, avatar_url=None, cover_url=None)
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
        ):
            response = await endpoint(
                request=SimpleNamespace(),
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


if __name__ == "__main__":
    unittest.main()
