from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.core.database import Base


class ModerationSurface(str, PyEnum):
    PROFILE_AVATAR = "profile_avatar"
    PROFILE_COVER = "profile_cover"
    PROFILE_DISPLAY_NAME = "profile_display_name"
    PROFILE_BIO = "profile_bio"
    POST_TEXT = "post_text"
    POST_MEDIA = "post_media"
    DM_TEXT = "dm_text"
    DM_MEDIA = "dm_media"


class ModerationDetectionStatus(str, PyEnum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"


class ModerationReviewStatus(str, PyEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ModerationSignal(Base):
    __tablename__ = "moderation_signals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True)
    dm_message_id = Column(Integer, ForeignKey("direct_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    surface_type = Column(
        SAEnum(
            ModerationSurface,
            name="moderationsurface",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    detection_status = Column(
        SAEnum(
            ModerationDetectionStatus,
            name="moderationdetectionstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    review_status = Column(
        SAEnum(
            ModerationReviewStatus,
            name="moderationreviewstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ModerationReviewStatus.OPEN,
        index=True,
    )
    reason_codes = Column(JSON, nullable=False, default=list)
    reason_summary = Column(String(500), nullable=False)
    risk_score = Column(Integer, nullable=False, default=0, index=True)
    content_preview = Column(Text, nullable=True)
    media_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    resolution_action = Column(String(100), nullable=True)
    resolution_note = Column(Text, nullable=True)

    actor_user = relationship("User", foreign_keys=[user_id])
    post = relationship("Post", foreign_keys=[post_id])
    dm_message = relationship("DirectMessage", foreign_keys=[dm_message_id])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by_user_id])
