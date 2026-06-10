from app.core.config import settings
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider


def get_storage_provider() -> StorageProvider:
    provider = settings.STORAGE_PROVIDER.lower()

    if provider == "local":
        return LocalStorageProvider()

    raise ValueError(
        f"Unsupported storage provider '{settings.STORAGE_PROVIDER}'. "
        "Only 'local' is configured currently."
    )
