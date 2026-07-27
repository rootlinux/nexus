from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    mfa_satisfied = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True, index=True)
    device_label = Column(String(255), nullable=True)
    # Short hash of stable client headers used at issuance. A mismatch on
    # refresh is now a recorded risk signal only (see refresh.fingerprint_changed
    # audit action) — it no longer forces revocation on its own.
    device_fingerprint = Column(String(32), nullable=True)

    # Replay-detection lineage — every token belongs to a family (rooted at
    # the login that started it); rotation chains parent -> child within a
    # family, and reuse of an already-rotated token revokes the whole family.
    token_family_id = Column(String(36), nullable=False, index=True)
    parent_token_id = Column(Integer, ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True, index=True)
    replaced_by_token_id = Column(Integer, ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True, index=True)
    reuse_detected_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    user = relationship("User", back_populates="refresh_tokens")
