from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredMedia:
    storage_key: str
    public_url: str


class StorageProvider(Protocol):
    async def save_file(self, *, content: bytes, content_type: str, original_filename: str | None = None) -> StoredMedia:
        ...

    def get_public_url(self, storage_key: str) -> str:
        ...

    async def delete_file(self, *, storage_key: str) -> None:
        ...
