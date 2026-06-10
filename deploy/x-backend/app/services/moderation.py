from __future__ import annotations

from datetime import datetime, timezone

from app.models.post import Post, PostModerationStatus
from app.models.user import User, UserStatus


def apply_user_status(
    user: User,
    *,
    status: UserStatus,
    actor_user_id: int,
    reason: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    user.status = status
    user.status_reason = reason
    user.status_changed_at = now
    user.status_changed_by_user_id = actor_user_id

    if status == UserStatus.BANNED:
        user.banned_at = now
        user.ban_reason = reason
        user.banned_by_user_id = actor_user_id
        user.is_active = False
    else:
        user.banned_at = None
        user.ban_reason = None
        user.banned_by_user_id = None
        user.is_active = True


def apply_post_moderation(
    post: Post,
    *,
    status: PostModerationStatus,
    actor_user_id: int,
    reason: str | None,
) -> None:
    post.moderation_status = status
    post.moderation_reason = reason
    post.moderated_at = datetime.now(timezone.utc)
    post.moderated_by_user_id = actor_user_id
