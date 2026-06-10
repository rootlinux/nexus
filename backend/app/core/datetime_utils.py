from datetime import datetime, timezone


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_naive_utc_datetime(value: datetime | None) -> datetime | None:
    normalized = ensure_utc_datetime(value)
    if normalized is None:
        return None
    return normalized.replace(tzinfo=None)
