from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer

from app.core.database import Base


class UserMediaQuota(Base):
    """One row per user, lazily created on first upload. Row-locked
    (SELECT ... FOR UPDATE, via _lock_quota_rows_ascending) and updated
    atomically in the same transaction as the MediaAsset insert it
    accompanies.

    file_count/total_bytes reflect bytes actually resident on disk — logical
    deletion (MediaAssetStatus.DELETION_PENDING) does NOT decrement either,
    since physical cleanup is dry-run only this round; only a future,
    separately-approved physical-deletion feature releases this quota, once
    it actually removes the file. Only daily_bytes is enforced this round
    (a rolling 24h window that resets on its own regardless of cleanup);
    file_count/total_bytes are tracked for reporting only, not enforced,
    since enforcing a lifetime cap with no way to recover from it would
    permanently strand any user who reaches it.
    """
    __tablename__ = "user_media_quota"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    file_count = Column(Integer, nullable=False, default=0)
    total_bytes = Column(Integer, nullable=False, default=0)
    daily_bytes = Column(Integer, nullable=False, default=0)
    daily_window_started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
