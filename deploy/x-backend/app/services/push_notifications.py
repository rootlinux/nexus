from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notification import Notification, NotificationType
from app.models.push_subscription import PushSubscription


class PushDeliveryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_expired(self) -> bool:
        return self.status_code in {404, 410}


@dataclass(slots=True)
class PushSendResult:
    sent_count: int = 0
    failed_count: int = 0


def web_push_is_configured() -> bool:
    return bool(
        settings.VAPID_PUBLIC_KEY.strip()
        and settings.VAPID_PRIVATE_KEY.strip()
        and settings.VAPID_SUBJECT.strip()
    )


async def list_push_subscriptions(
    db: AsyncSession,
    *,
    user_id: int,
    include_inactive: bool = True,
) -> list[PushSubscription]:
    filters = [PushSubscription.user_id == user_id]
    if not include_inactive:
        filters.append(PushSubscription.is_active.is_(True))
    result = await db.execute(
        select(PushSubscription)
        .where(*filters)
        .order_by(PushSubscription.id.asc())
    )
    return list(result.scalars().all())


async def upsert_push_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    normalized_endpoint = endpoint.strip()
    now = datetime.utcnow()
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == normalized_endpoint))
    subscription = result.scalar_one_or_none()
    if subscription is None:
        subscription = PushSubscription(
            user_id=user_id,
            endpoint=normalized_endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            last_seen_at=now,
            is_active=True,
        )
        db.add(subscription)
    else:
        subscription.user_id = user_id
        subscription.p256dh = p256dh
        subscription.auth = auth
        subscription.user_agent = user_agent
        subscription.last_seen_at = now
        subscription.last_failure_at = None
        subscription.is_active = True
    await db.flush()
    return subscription


async def delete_push_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    endpoint: str,
) -> int:
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint.strip(),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        return 0
    await db.delete(subscription)
    await db.flush()
    return 1


async def deactivate_push_subscription(
    db: AsyncSession,
    subscription: PushSubscription,
    *,
    failed_at: datetime | None = None,
) -> None:
    subscription.is_active = False
    subscription.last_failure_at = failed_at or datetime.utcnow()
    await db.flush()


def notification_type_to_setting_field(notification_type: NotificationType) -> str:
    mapping = {
        NotificationType.LIKE: "push_likes",
        NotificationType.REPLY: "push_replies",
        NotificationType.REPOST: "push_reposts",
        NotificationType.MENTION: "push_mentions",
        NotificationType.FOLLOW: "push_follows",
        NotificationType.QUOTE: "push_mentions",
    }
    return mapping[notification_type]


def notification_copy(notification: Notification) -> str:
    actor_name = notification.actor_user.display_name or notification.actor_user.username
    mapping = {
        NotificationType.LIKE: "liked your post",
        NotificationType.REPOST: "reposted your post",
        NotificationType.QUOTE: "quoted your post",
        NotificationType.FOLLOW: "followed you",
        NotificationType.REPLY: "replied to your post",
        NotificationType.MENTION: "mentioned you",
    }
    return f"{actor_name} {mapping[notification.notification_type]}"


def notification_body(notification: Notification) -> str:
    if notification.source_post and notification.source_post.content:
        return " ".join(notification.source_post.content.split())[:140]
    if notification.post and notification.post.content:
        return " ".join(notification.post.content.split())[:140]
    return "Open the app to catch up."


def notification_target_url(notification: Notification) -> str:
    if notification.notification_type in {NotificationType.REPLY, NotificationType.MENTION, NotificationType.QUOTE}:
        target_post = notification.source_post or notification.post
    else:
        target_post = notification.post or notification.source_post

    if target_post and target_post.id:
        query = "entry=notifications"
        if notification.notification_type == NotificationType.QUOTE:
            query += "&focus=quote"
        elif notification.notification_type in {NotificationType.REPLY, NotificationType.MENTION}:
            query += "&focus=reply"
        return f"/post/{target_post.id}?{query}"

    return f"/{quote(notification.actor_user.username.strip())}"


def build_notification_push_payload(notification: Notification) -> dict[str, Any]:
    return {
        "title": notification_copy(notification),
        "body": notification_body(notification),
        "message": notification_body(notification),
        "url": notification_target_url(notification),
        "tag": f"notification-{notification.id}",
        "notification_id": notification.id,
        "notification_type": notification.notification_type.value,
        "icon": "/icon-192.png",
        "badge": "/icon-192.png",
    }


async def send_web_push_message(subscription: PushSubscription, payload: dict[str, Any]) -> None:
    try:
        from pywebpush import WebPushException, webpush
    except ImportError as exc:
        raise PushDeliveryError("pywebpush is not installed") from exc

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
        )
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        raise PushDeliveryError(str(exc), status_code=status_code) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback around third-party send path
        raise PushDeliveryError(str(exc)) from exc


async def send_push_payload_to_user(
    db: AsyncSession,
    *,
    user_id: int,
    payload: dict[str, Any],
) -> PushSendResult:
    result = PushSendResult()
    if not web_push_is_configured():
        return result

    subscriptions = await list_push_subscriptions(db, user_id=user_id, include_inactive=False)
    for subscription in subscriptions:
        try:
            await send_web_push_message(subscription, payload)
        except PushDeliveryError as exc:
            result.failed_count += 1
            if exc.is_expired:
                await deactivate_push_subscription(db, subscription)
            else:
                subscription.last_failure_at = datetime.utcnow()
                await db.flush()
        else:
            subscription.last_success_at = datetime.utcnow()
            subscription.last_failure_at = None
            subscription.is_active = True
            result.sent_count += 1
            await db.flush()
    return result
