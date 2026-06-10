from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User, UserStatus
from app.services.staff_permissions import apply_staff_permission_updates

logger = logging.getLogger("app.bootstrap")


async def bootstrap_admin_if_configured() -> None:
    if not settings.ENABLE_BOOTSTRAP_ADMIN:
        return

    async with AsyncSessionLocal() as session:
        existing_staff_count = await session.scalar(select(func.count()).select_from(StaffPermission))
        if existing_staff_count:
            logger.info(
                "Skipping bootstrap admin creation because a staff account already exists",
                extra={"existing_staff_count": int(existing_staff_count)},
            )
            return

        existing_user = await session.scalar(
            select(User).where(
                or_(
                    User.username == settings.BOOTSTRAP_ADMIN_USERNAME,
                    User.email == settings.BOOTSTRAP_ADMIN_EMAIL,
                )
            )
        )
        if existing_user is not None:
            logger.warning(
                "Skipping bootstrap admin creation because the requested bootstrap identity already exists without a staff record",
                extra={"user_id": existing_user.id, "username": existing_user.username},
            )
            return

        now = datetime.now(timezone.utc)
        user = User(
            username=settings.BOOTSTRAP_ADMIN_USERNAME.strip(),
            email=settings.BOOTSTRAP_ADMIN_EMAIL.strip(),
            password_hash=get_password_hash(settings.BOOTSTRAP_ADMIN_PASSWORD),
            display_name=(settings.BOOTSTRAP_ADMIN_DISPLAY_NAME or settings.BOOTSTRAP_ADMIN_USERNAME).strip(),
            created_at=now,
            is_active=True,
            must_change_password=False,
            email_verified_at=now,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()

        staff_permission = StaffPermission(user_id=user.id)
        apply_staff_permission_updates(
            staff_permission,
            role=StaffRole.SUPER_ADMIN,
            invite_quota_monthly=None,
            updates={},
            updated_by_user_id=user.id,
        )
        user.staff_permission = staff_permission
        session.add(staff_permission)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning("Bootstrap admin creation raced with another process; leaving existing state unchanged")
            return

        logger.warning(
            "Created one-time bootstrap admin because ENABLE_BOOTSTRAP_ADMIN was set in a local/dev/test environment",
            extra={"user_id": user.id, "username": user.username},
        )
