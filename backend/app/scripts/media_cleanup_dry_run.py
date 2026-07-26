from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
# Registers every model class the declarative registry needs to resolve
# string-referenced relationships. app.models's own __init__ doesn't import
# webauthn_credential at all (confirmed directly — not just app.models
# itself is insufficient here), so any query touching User — even
# transitively — hits a mapper-configuration error the moment SQLAlchemy
# tries to resolve User.webauthn_credentials, since this script's entry
# point never imports app.main / the full app the way the running
# application always does.
import app.models  # noqa: F401
import app.models.webauthn_credential  # noqa: F401
from app.models.media_asset import MediaAsset, MediaAssetType
from app.services.media_assets import find_cleanup_candidates

def _media_type_local_dir() -> dict:
    """media_type -> local directory the file would live in, for the
    untracked-legacy cross-reference below. Matches the same two roots the
    rest of the app already writes to (LocalStorageProvider default vs. the
    feedback-specific override in feedback.py::_get_feedback_storage_provider).
    Built fresh on every call (not a module-level constant) so it reflects
    the current settings values, not whatever they were at import time."""
    return {
        MediaAssetType.AVATAR: settings.LOCAL_UPLOAD_DIR,
        MediaAssetType.COVER: settings.LOCAL_UPLOAD_DIR,
        MediaAssetType.POST_IMAGE: settings.LOCAL_UPLOAD_DIR,
        MediaAssetType.FEEDBACK_ATTACHMENT: settings.FEEDBACK_ATTACHMENT_LOCAL_DIR,
    }


def _resolve_dir(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


async def _find_untracked_legacy_files(db) -> dict[str, list[str]]:
    """DRY-RUN, read-only: cross-references tracked MediaAsset.storage_key
    values against files actually present on disk, in the two known local
    directories. Never touches backend/uploads/ or
    backend/feedback_private_uploads/ beyond listing filenames — no read of
    file contents, no writes, no deletes."""
    tracked_keys = set((await db.scalars(select(MediaAsset.storage_key))).all())
    media_type_local_dir = _media_type_local_dir()

    files_without_db_row: list[str] = []
    seen_dirs: set[Path] = set()
    for raw_dir in media_type_local_dir.values():
        directory = _resolve_dir(raw_dir)
        if directory in seen_dirs or not directory.is_dir():
            continue
        seen_dirs.add(directory)
        for entry in directory.iterdir():
            if entry.is_file() and entry.name not in tracked_keys:
                files_without_db_row.append(str(entry.relative_to(directory.parent)))

    db_rows_without_file: list[str] = []
    asset_rows = (await db.execute(select(MediaAsset.storage_key, MediaAsset.media_type))).all()
    for storage_key, media_type in asset_rows:
        directory = _resolve_dir(media_type_local_dir[media_type])
        if not (directory / storage_key).is_file():
            db_rows_without_file.append(storage_key)

    return {
        "files_without_db_row": sorted(files_without_db_row),
        "db_rows_without_file": sorted(db_rows_without_file),
    }


async def _run() -> dict:
    async with AsyncSessionLocal() as db:
        report = await find_cleanup_candidates(db)
        untracked = await _find_untracked_legacy_files(db)

    return {
        "generated_at": report.generated_at.isoformat(),
        "mode": "DRY-RUN — no files are ever deleted by this script",
        "expired_pending": [
            {
                "id": item.id, "owner_user_id": item.owner_user_id,
                "storage_key": item.storage_key, "created_at": item.created_at.isoformat(),
            }
            for item in report.expired_pending
        ],
        "orphaned_deletion_pending": {
            "note": (
                "These MediaAsset rows are logically DELETION_PENDING, but the physical "
                "file still exists on disk (dry-run-only cleanup this round). Not safe to "
                "fully forget — a future, separately-approved physical-deletion feature "
                "would need to actually remove these files."
            ),
            "items": [
                {
                    "id": item.id, "owner_user_id": item.owner_user_id,
                    "storage_key": item.storage_key,
                    "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
                }
                for item in report.orphaned_deletion_pending
            ],
        },
        "users_over_lifetime_limits": {
            "note": (
                "MEDIA_MAX_FILES_PER_USER / MEDIA_MAX_TOTAL_BYTES_PER_USER are tracked but "
                "not enforced this round. These users already exceed the proposed limits."
            ),
            "items": [
                {"user_id": item.user_id, "file_count": item.file_count, "total_bytes": item.total_bytes}
                for item in report.users_over_lifetime_limits
            ],
        },
        "untracked_legacy": {
            "note": (
                "Pre-migration files/rows with no counterpart on the other side. Not "
                "conflated with the tracked cleanup candidates above — these predate "
                "media_assets entirely and are handled by the existing legacy-compat paths, "
                "not by this script."
            ),
            **untracked,
        },
    }


def main() -> int:
    report = asyncio.run(_run())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
