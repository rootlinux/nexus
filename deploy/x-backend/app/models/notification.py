from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class NotificationType(str, PyEnum):
    LIKE = "like"
    REPOST = "repost"
    QUOTE = "quote"
    FOLLOW = "follow"
    REPLY = "reply"
    MENTION = "mention"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type = Column(
        SAEnum(
            NotificationType,
            name="notificationtype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    source_post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    read_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="notifications")
    actor_user = relationship("User", foreign_keys=[actor_user_id], back_populates="acted_notifications")
    post = relationship("Post", foreign_keys=[post_id], back_populates="notifications")
    source_post = relationship("Post", foreign_keys=[source_post_id], back_populates="source_notifications")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "actor_user_id",
            "notification_type",
            "post_id",
            "source_post_id",
            name="uq_notification_dedupe",
        ),
    )
