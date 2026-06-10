from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notification import Notification, NotificationType
from app.models.notification_settings import NotificationSettings
from app.models.post import Post
from app.models.user import User
from app.services.blocks import get_block_relationship
from app.services.post_views import annotate_posts_for_user, is_post_visible_to_viewer, post_query_options
from app.services.push_notifications import (
    build_notification_push_payload,
    notification_type_to_setting_field,
    send_push_payload_to_user,
    web_push_is_configured,
)
from app.schemas.notification import NotificationActorRead, NotificationPostContextRead, NotificationRead

MENTION_PATTERN = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{3,20})")


async def get_or_create_notification_settings(db: AsyncSession, user_id: int) -> NotificationSettings:
    result = await db.execute(select(NotificationSettings).where(NotificationSettings.user_id == user_id))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = NotificationSettings(user_id=user_id)
    db.add(settings)
    await db.flush()
    return settings


async def create_notification(
    db: AsyncSession,
    *,
    recipient_user_id: int,
    actor_user_id: int,
    notification_type: NotificationType,
    post_id: int | None = None,
    source_post_id: int | None = None,
) -> Notification | None:
    if recipient_user_id == actor_user_id:
        return None

    if (await get_block_relationship(db, current_user_id=actor_user_id, target_user_id=recipient_user_id)).is_blocked:
        return None

    existing_result = await db.execute(
        select(Notification).where(
            Notification.user_id == recipient_user_id,
            Notification.actor_user_id == actor_user_id,
            Notification.notification_type == notification_type,
            Notification.post_id == post_id,
            Notification.source_post_id == source_post_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    notification = Notification(
        user_id=recipient_user_id,
        actor_user_id=actor_user_id,
        notification_type=notification_type,
        post_id=post_id,
        source_post_id=source_post_id,
    )
    db.add(notification)
    await db.flush()
    await _maybe_send_push_notification(db, notification)
    return notification


async def _maybe_send_push_notification(db: AsyncSession, notification: Notification) -> None:
    if not web_push_is_configured():
        return

    settings = await get_or_create_notification_settings(db, notification.user_id)
    setting_name = notification_type_to_setting_field(notification.notification_type)
    if not getattr(settings, setting_name, False):
        return

    result = await db.execute(
        select(Notification)
        .options(*notification_query_options())
        .where(Notification.id == notification.id)
    )
    loaded_notification = result.scalar_one()
    await annotate_notification_posts(db, [loaded_notification], loaded_notification.user_id)
    payload = build_notification_push_payload(loaded_notification)
    await send_push_payload_to_user(
        db,
        user_id=loaded_notification.user_id,
        payload=payload,
    )


def extract_mentions(content: str) -> set[str]:
    return {username.lower() for username in MENTION_PATTERN.findall(content or "")}


async def create_follow_notification(db: AsyncSession, *, actor_user_id: int, target_user_id: int) -> None:
    await create_notification(
        db,
        recipient_user_id=target_user_id,
        actor_user_id=actor_user_id,
        notification_type=NotificationType.FOLLOW,
    )


async def create_like_notification(db: AsyncSession, *, actor_user_id: int, target_post: Post) -> None:
    await create_notification(
        db,
        recipient_user_id=target_post.user_id,
        actor_user_id=actor_user_id,
        notification_type=NotificationType.LIKE,
        post_id=target_post.id,
        source_post_id=target_post.id,
    )


async def create_repost_notification(db: AsyncSession, *, actor_user_id: int, target_post: Post) -> None:
    await create_notification(
        db,
        recipient_user_id=target_post.user_id,
        actor_user_id=actor_user_id,
        notification_type=NotificationType.REPOST,
        post_id=target_post.id,
        source_post_id=target_post.id,
    )


async def create_quote_notification(db: AsyncSession, *, actor_user_id: int, target_post: Post, quote_post: Post) -> None:
    await create_notification(
        db,
        recipient_user_id=target_post.user_id,
        actor_user_id=actor_user_id,
        notification_type=NotificationType.QUOTE,
        post_id=target_post.id,
        source_post_id=quote_post.id,
    )


async def create_reply_notifications(db: AsyncSession, *, actor_user_id: int, parent_post: Post, reply_post: Post) -> None:
    await create_notification(
        db,
        recipient_user_id=parent_post.user_id,
        actor_user_id=actor_user_id,
        notification_type=NotificationType.REPLY,
        post_id=parent_post.id,
        source_post_id=reply_post.id,
    )


async def create_mention_notifications(db: AsyncSession, *, actor_user_id: int, source_post: Post) -> None:
    mentioned_usernames = extract_mentions(source_post.content or "")
    if not mentioned_usernames:
        return

    users_result = await db.execute(
        select(User).where(or_(*(User.username.ilike(username) for username in mentioned_usernames)))
    )
    for user in users_result.scalars().all():
        await create_notification(
            db,
            recipient_user_id=user.id,
            actor_user_id=actor_user_id,
            notification_type=NotificationType.MENTION,
            post_id=source_post.id,
            source_post_id=source_post.id,
        )


def notification_query_options():
    return (
        selectinload(Notification.actor_user),
        selectinload(Notification.post).options(*post_query_options()),
        selectinload(Notification.source_post).options(*post_query_options()),
    )


def _user_to_read(user: User) -> NotificationActorRead:
    return NotificationActorRead(
        id=user.id,
        username=user.username,
        display_name=getattr(user, "display_name", None),
        avatar_url=getattr(user, "avatar_url", None),
    )


def _content_snippet(content: str | None, limit: int = 140) -> str | None:
    normalized = " ".join((content or "").split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _notification_post_context(post: Post | None) -> NotificationPostContextRead | None:
    if not post:
        return None

    if not is_post_visible_to_viewer(post):
        return NotificationPostContextRead(
            id=None,
            content_snippet=None,
            author_username=None,
            author_display_name=None,
            is_quote=bool(post.quoted_post_id),
            is_reply=post.parent_id is not None,
            is_available=False,
            unavailable_reason="This post is no longer available.",
        )

    return NotificationPostContextRead(
        id=post.id,
        content_snippet=_content_snippet(post.content),
        author_username=post.author.username,
        author_display_name=getattr(post.author, "display_name", None),
        is_quote=bool(post.quoted_post_id),
        is_reply=post.parent_id is not None,
        is_available=True,
        unavailable_reason=None,
    )


def notification_to_read(notification: Notification, current_user_id: int | None = None) -> NotificationRead:
    return NotificationRead(
        id=notification.id,
        notification_type=notification.notification_type,
        created_at=notification.created_at,
        read_at=notification.read_at,
        is_unread=notification.read_at is None,
        actor=_user_to_read(notification.actor_user),
        post=_notification_post_context(notification.post),
        source_post=_notification_post_context(notification.source_post),
    )


async def annotate_notification_posts(
    db: AsyncSession,
    notifications: Sequence[Notification],
    current_user_id: int | None,
) -> None:
    posts: list[Post] = []
    for notification in notifications:
        if notification.post:
            posts.append(notification.post)
        if notification.source_post:
            posts.append(notification.source_post)
    await annotate_posts_for_user(db, posts, current_user_id)


async def mark_notifications_read(db: AsyncSession, notifications: Iterable[Notification]) -> datetime:
    timestamp: datetime | None = None
    first_existing: datetime | None = None
    for notification in notifications:
        if notification.read_at is None:
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)
            notification.read_at = timestamp
        elif first_existing is None:
            first_existing = notification.read_at
    await db.flush()
    return timestamp or first_existing or datetime.now(timezone.utc)
