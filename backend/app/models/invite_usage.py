from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class InviteUsage(Base):
    __tablename__ = "invite_usages"

    id = Column(Integer, primary_key=True, index=True)
    invite_id = Column(Integer, ForeignKey("invite_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("used_by_user_id", name="uq_invite_usages_used_by_user_id"),
    )

    invite = relationship("InviteCode", back_populates="usages")
    used_by_user = relationship("User", back_populates="invite_usages", foreign_keys=[used_by_user_id])
