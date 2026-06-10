import re
from pathlib import Path
import uuid

from fastapi import HTTPException

from app.core.config import settings
from app.storage.base import StoredMedia, StorageProvider

STORAGE_KEY_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z0-9]{2,5}$')


class LocalStorageProvider(StorageProvider):
    def __init__(self, upload_dir: str | None = None, url_prefix: str | None = None):
        configured_dir = Path(upload_dir or settings.LOCAL_UPLOAD_DIR)
        if configured_dir.is_absolute():
            self.upload_dir = configured_dir
        else:
            backend_root = Path(__file__).resolve().parents[2]
            self.upload_dir = (backend_root / configured_dir).resolve()
        self.url_prefix = (url_prefix or settings.LOCAL_UPLOAD_URL_PREFIX).rstrip("/")

    async def save_file(self, *, content: bytes, content_type: str, original_filename: str | None = None) -> StoredMedia:
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        storage_key = f"{uuid.uuid4()}{self._get_extension(content_type)}"
        file_path = self.upload_dir / storage_key

        try:
            file_path.write_bytes(content)
        except Exception:
            if file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            raise

        return StoredMedia(
            storage_key=storage_key,
            public_url=self.get_public_url(storage_key),
        )

    def get_public_url(self, storage_key: str) -> str:
        return f"{self.url_prefix}/{storage_key}"

    async def delete_file(self, *, storage_key: str) -> None:
        file_path = self.resolve_storage_path(storage_key)
        try:
            file_path.unlink(missing_ok=True)
        except TypeError:
            if file_path.exists():
                file_path.unlink()

    def get_static_mount_directory(self) -> str:
        return str(self.upload_dir)

    def resolve_storage_path(self, storage_key: str) -> Path:
        if not STORAGE_KEY_RE.fullmatch(storage_key):
            raise HTTPException(status_code=400, detail="Invalid storage key format")

        file_path = self.upload_dir / storage_key
        resolved = file_path.resolve()
        upload_resolved = self.upload_dir.resolve()
        if not resolved.is_relative_to(upload_resolved):
            raise ValueError(f"storage_key escapes upload directory: {storage_key}")
        return resolved

    @staticmethod
    def _get_extension(content_type: str) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(content_type, ".jpg")
