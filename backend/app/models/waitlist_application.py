from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class WaitlistApplicationStatus(str, PyEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class WaitlistApplication(Base):
    __tablename__ = "waitlist_applications"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    contact = Column(String(255), nullable=False, index=True)
    preferred_username = Column(String(50), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    referral_source = Column(String(255), nullable=True)
    social_url = Column(String(500), nullable=True)
    status = Column(
        SAEnum(
            WaitlistApplicationStatus,
            name="waitlistapplicationstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=WaitlistApplicationStatus.NEW,
        index=True,
    )
    admin_notes = Column(Text, nullable=True)
    invite_id = Column(Integer, ForeignKey("invite_codes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    invite = relationship("InviteCode", foreign_keys=[invite_id])

    __table_args__ = (
        Index("ix_waitlist_applications_created_at", "created_at"),
    )