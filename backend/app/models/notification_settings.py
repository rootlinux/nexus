from sqlalchemy import Boolean, Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    push_likes = Column(Boolean, nullable=False, default=True)
    push_replies = Column(Boolean, nullable=False, default=True)
    push_reposts = Column(Boolean, nullable=False, default=True)
    push_mentions = Column(Boolean, nullable=False, default=True)
    push_follows = Column(Boolean, nullable=False, default=True)
    email_likes = Column(Boolean, nullable=False, default=False)
    email_replies = Column(Boolean, nullable=False, default=False)
    email_reposts = Column(Boolean, nullable=False, default=False)
    email_mentions = Column(Boolean, nullable=False, default=False)
    email_follows = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="notification_settings")
