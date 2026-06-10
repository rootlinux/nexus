from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class StaleFeedbackAttachment:
    path: Path
    age_days: float
    size_bytes: int


def find_stale_feedback_attachments(
    root: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[StaleFeedbackAttachment]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    if not root.exists():
        return []

    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    stale_files: list[StaleFeedbackAttachment] = []

    for path in root.rglob('*'):
        if not path.is_file():
            continue

        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified_at >= cutoff:
            continue

        age_days = max((current_time - modified_at).total_seconds() / 86400, 0)
        stale_files.append(
            StaleFeedbackAttachment(
                path=path,
                age_days=age_days,
                size_bytes=path.stat().st_size,
            )
        )

    stale_files.sort(key=lambda item: item.path.as_posix())
    return stale_files


def delete_feedback_attachments(items: list[StaleFeedbackAttachment]) -> int:
    deleted = 0
    for item in items:
        if not item.path.exists():
            continue
        item.path.unlink()
        deleted += 1
    return deleted
