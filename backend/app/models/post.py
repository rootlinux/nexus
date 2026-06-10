from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class PostModerationStatus(str, PyEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    DELETED = "deleted"


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    media_url = Column(String(500), nullable=True)
    parent_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)
    repost_of_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)
    quoted_post_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)
    is_repost = Column(Boolean, default=False, nullable=False)
    likes_count = Column(Integer, default=0, nullable=False)
    replies_count = Column(Integer, default=0, nullable=False)
    reposts_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    moderation_status = Column(
        SAEnum(
            PostModerationStatus,
            name="postmoderationstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PostModerationStatus.VISIBLE,
        index=True,
    )
    moderation_reason = Column(String(500), nullable=True)
    moderated_at = Column(DateTime(timezone=True), nullable=True)
    moderated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Relationships
    author = relationship("User", back_populates="posts", foreign_keys=[user_id])
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    bookmarks = relationship("Bookmark", back_populates="post", cascade="all, delete-orphan")
    notifications = relationship("Notification", foreign_keys="Notification.post_id", back_populates="post", cascade="all, delete-orphan")
    source_notifications = relationship("Notification", foreign_keys="Notification.source_post_id", back_populates="source_post", cascade="all, delete-orphan")
    moderation_signals = relationship("ModerationSignal", foreign_keys="ModerationSignal.post_id", back_populates="post")
    moderated_by = relationship("User", foreign_keys=[moderated_by_user_id])

    parent = relationship(
        "Post",
        foreign_keys="[Post.parent_id]",
        remote_side="[Post.id]",
        backref="replies"
    )

    repost_of = relationship(
        "Post",
        foreign_keys="[Post.repost_of_id]",
        remote_side="[Post.id]",
        backref="reposts"
    )

    quoted_post = relationship(
        "Post",
        foreign_keys="[Post.quoted_post_id]",
        remote_side="[Post.id]",
        backref="quotes"
    )
