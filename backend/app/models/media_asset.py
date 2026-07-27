from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum

from app.core.database import Base


class MediaAssetType(str, PyEnum):
    AVATAR = "avatar"
    COVER = "cover"
    POST_IMAGE = "post_image"
    FEEDBACK_ATTACHMENT = "feedback_attachment"


class MediaAssetStatus(str, PyEnum):
    PENDING = "pending"
    ATTACHED = "attached"
    DELETION_PENDING = "deletion_pending"  # logical deletion only — the physical file
                                            # still exists on disk (dry-run-only cleanup
                                            # this round); a genuine DELETED value belongs
                                            # to a future, separately-approved physical-
                                            # cleanup migration, not reserved here.


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    media_type = Column(
        SAEnum(MediaAssetType, name="mediaassettype", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    storage_key = Column(String(255), nullable=False, unique=True, index=True)
    storage_provider = Column(String(32), nullable=False, default="local")
    content_type = Column(String(64), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    status = Column(
        SAEnum(MediaAssetStatus, name="mediaassetstatus", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=MediaAssetStatus.PENDING, index=True,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    attached_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    attached_to_type = Column(String(32), nullable=True)  # "user_avatar" | "user_cover" | "post" | "feedback_report"
    attached_to_id = Column(Integer, nullable=True)  # polymorphic; no DB FK, target table varies

    __table_args__ = (
        Index("ix_media_assets_owner_status", "owner_user_id", "status"),
        Index("ix_media_assets_status_created_at", "status", "created_at"),
        Index("ix_media_assets_attached_to", "attached_to_type", "attached_to_id"),
    )
