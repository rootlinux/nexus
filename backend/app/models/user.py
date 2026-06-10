from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserStatus(str, PyEnum):
    """Enum for user moderation status."""
    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"
    BANNED = "banned"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=True)  # Optional display name
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    cover_url = Column(String(500), nullable=True)
    bio = Column(String(500), nullable=True)
    location = Column(String(100), nullable=True)
    website = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False, index=True)
    email_verified_at = Column(DateTime, nullable=True, index=True)

    # === Moderation Fields ===
    status = Column(
        SAEnum(
            UserStatus,
            name="userstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=UserStatus.ACTIVE,
        index=True,
    )
    banned_at = Column(DateTime, nullable=True)
    ban_reason = Column(String(500), nullable=True)
    banned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status_reason = Column(String(500), nullable=True)
    status_changed_at = Column(DateTime, nullable=True)
    status_changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # === Invite Traceability Fields ===
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    invite_id_used = Column(Integer, ForeignKey("invite_codes.id"), nullable=True, index=True)

    # Relationships
    created_invites = relationship("InviteCode", back_populates="created_by_user", foreign_keys="InviteCode.created_by_id")
    generated_campaign_invites = relationship(
        "InviteCode",
        back_populates="generated_by_user",
        foreign_keys="InviteCode.generated_by_user_id",
    )
    assigned_invites = relationship("InviteCode", back_populates="assigned_to_user", foreign_keys="InviteCode.assigned_to_user_id")
    used_invite_codes = relationship("InviteCode", back_populates="used_by_user", foreign_keys="InviteCode.used_by_user_id")
    invite_usages = relationship("InviteUsage", back_populates="used_by_user", foreign_keys="InviteUsage.used_by_user_id")
    posts = relationship(
        "Post",
        back_populates="author",
        cascade="all, delete-orphan",
        foreign_keys="Post.user_id",
    )
    likes = relationship("Like", back_populates="user", cascade="all, delete-orphan")
    bookmarks = relationship("Bookmark", back_populates="user", cascade="all, delete-orphan")
    following = relationship("Follow", foreign_keys="Follow.follower_id", back_populates="follower", cascade="all, delete-orphan")
    followers = relationship("Follow", foreign_keys="Follow.following_id", back_populates="following", cascade="all, delete-orphan")
    blocking = relationship("Block", foreign_keys="Block.blocker_id", back_populates="blocker", cascade="all, delete-orphan")
    blocked_by = relationship("Block", foreign_keys="Block.blocked_id", back_populates="blocked", cascade="all, delete-orphan")
    sent_messages = relationship("DirectMessage", foreign_keys="DirectMessage.sender_id", back_populates="sender", cascade="all, delete-orphan")
    received_messages = relationship("DirectMessage", foreign_keys="DirectMessage.receiver_id", back_populates="receiver", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    email_change_tokens = relationship("EmailChangeToken", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", foreign_keys="Notification.user_id", back_populates="user", cascade="all, delete-orphan")
    notification_settings = relationship("NotificationSettings", back_populates="user", cascade="all, delete-orphan", uselist=False)
    push_subscriptions = relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")
    acted_notifications = relationship("Notification", foreign_keys="Notification.actor_user_id", back_populates="actor_user")
    moderation_signals = relationship("ModerationSignal", foreign_keys="ModerationSignal.user_id", back_populates="actor_user")
    resolved_moderation_signals = relationship("ModerationSignal", foreign_keys="ModerationSignal.resolved_by_user_id", back_populates="resolved_by_user")
    staff_permission = relationship(
        "StaffPermission",
        foreign_keys="StaffPermission.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    webauthn_credentials = relationship(
        "WebAuthnCredential",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # Moderation relationships
    banned_by = relationship("User", foreign_keys=[banned_by_user_id], remote_side=[id], backref="banned_users")
    status_changed_by = relationship("User", foreign_keys=[status_changed_by_user_id], remote_side=[id], backref="status_changed_users")
    inviter = relationship("User", foreign_keys=[invited_by_user_id], remote_side=[id], backref="invited_users")
    invite_used = relationship("InviteCode", foreign_keys=[invite_id_used], backref="used_by_new_user")

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None
