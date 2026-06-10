from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base


class InviteType(str, PyEnum):
    """Legacy enum retained for DB compatibility."""
    GENERIC = "generic"
    PERSONAL = "personal"
    REFERRAL = "referral"


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    code_hash = Column(String(64), unique=True, nullable=True, index=True)
    invite_type = Column(
        SAEnum(
            InviteType,
            name="invitetype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=InviteType.GENERIC,
        index=True,
    )
    
    # Creator info (admin-created only in active product flow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    generated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    campaign_id = Column(Integer, ForeignKey("invite_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    internal_note = Column(String(255), nullable=True)

    # Optional assignment to an existing user account that can share this invite.
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_to_username = Column(String(50), nullable=True, index=True)
    
    # Usage tracking
    max_uses = Column(Integer, default=1, nullable=False)
    current_uses = Column(Integer, default=0, nullable=False)
    
    # Who used this invite (for tracking)
    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    
    # Expiration and status
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    created_by_user = relationship("User", back_populates="created_invites", foreign_keys=[created_by_id])
    generated_by_user = relationship("User", back_populates="generated_campaign_invites", foreign_keys=[generated_by_user_id])
    assigned_to_user = relationship("User", back_populates="assigned_invites", foreign_keys=[assigned_to_user_id])
    used_by_user = relationship("User", back_populates="used_invite_codes", foreign_keys=[used_by_user_id])
    campaign = relationship("InviteCampaign", back_populates="invites")
    usages = relationship("InviteUsage", back_populates="invite", cascade="all, delete-orphan")
