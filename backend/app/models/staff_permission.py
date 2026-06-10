from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.core.database import Base


class StaffRole(str, PyEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"


class StaffPermission(Base):
    __tablename__ = "staff_permissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    role = Column(
        SAEnum(
            StaffRole,
            name="staffrole",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    can_create_invites = Column(Boolean, nullable=False, default=False)
    invite_quota_monthly = Column(Integer, nullable=True, default=0)
    can_view_moderation_queue = Column(Boolean, nullable=False, default=False)
    can_moderate_posts = Column(Boolean, nullable=False, default=False)
    can_manage_invites = Column(Boolean, nullable=False, default=False)
    can_manage_users = Column(Boolean, nullable=False, default=False)
    can_suspend_users = Column(Boolean, nullable=False, default=False)
    can_ban_users = Column(Boolean, nullable=False, default=False)
    can_manage_moderators = Column(Boolean, nullable=False, default=False)
    can_reset_passwords = Column(Boolean, nullable=False, default=False)
    can_revoke_sessions = Column(Boolean, nullable=False, default=False)
    can_create_wave_campaigns = Column(Boolean, nullable=False, default=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id], back_populates="staff_permission")
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])
