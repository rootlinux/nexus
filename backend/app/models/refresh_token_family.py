from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String
from app.core.database import Base


class RefreshTokenFamily(Base):
    """One row per refresh-token family, created alongside the family's
    first RefreshToken (on login, or by the 040 migration's backfill for
    pre-existing tokens). Its only purpose is to be the lock target every
    family-touching operation (ordinary rotation, family-wide replay
    revocation) contends on via SELECT ... FOR UPDATE — it carries no
    other state. See app/services/refresh_token_replay.py."""

    __tablename__ = "refresh_token_families"

    token_family_id = Column(String(36), primary_key=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
