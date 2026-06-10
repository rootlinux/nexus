from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits
from app.models.notification import Notification, NotificationType
from app.schemas.notification import (
    NotificationListResponse,
    NotificationMarkReadResponse,
    NotificationSettingsRead,
    NotificationSettingsUpdate,
    PushSubscriptionDeleteRequest,
    PushSubscriptionDeleteResponse,
    PushSubscriptionListResponse,
    PushSubscriptionUpsertRequest,
    PushSubscriptionUpsertResponse,
    PushTestSendRequest,
    PushTestSendResponse,
)
from app.services.blocks import get_blocked_user_ids
from app.services.notifications import (
    annotate_notification_posts,
    get_or_create_notification_settings,
    mark_notifications_read,
    notification_query_options,
    notification_to_read,
)
from app.services.push_notifications import (
    delete_push_subscription,
    list_push_subscriptions,
    send_push_payload_to_user,
    upsert_push_subscription,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_read_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="notification-read",
            limit=60,
            window_seconds=300,
            key=build_scope_key("notifications", "read", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _notification_read_all_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="notification-read-all",
            limit=10,
            window_seconds=300,
            key=build_scope_key("notifications", "read-all", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _notification_list_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="notifications-list",
            limit=60,
            window_seconds=60,
            key=build_scope_key("notifications", "list", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _notification_settings_update_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="notifications-settings-update",
            limit=10,
            window_seconds=60,
            key=build_scope_key("notifications", "settings", "update", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _push_subscription_write_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="push-subscriptions-write",
            limit=20,
            window_seconds=300,
            key=build_scope_key("notifications", "push-subscriptions", "write", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _push_subscription_read_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="push-subscriptions-read",
            limit=60,
            window_seconds=300,
            key=build_scope_key("notifications", "push-subscriptions", "read", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _push_test_send_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="push-subscriptions-test-send",
            limit=10,
            window_seconds=300,
            key=build_scope_key("notifications", "push-subscriptions", "test-send", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    request: Request,
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    tab: str = Query("all", pattern="^(all|mentions)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _notification_list_policies(current_user.id))
    base_filters = [Notification.user_id == current_user.id]
    if tab == "mentions":
        base_filters.append(Notification.notification_type == NotificationType.MENTION)

    total_result = await db.execute(select(func.count(Notification.id)).where(*base_filters))
    total = int(total_result.scalar() or 0)

    filters = list(base_filters)
    if cursor:
        filters.append(Notification.id < cursor)

    result = await db.execute(
        select(Notification)
        .options(*notification_query_options())
        .where(*filters)
        .order_by(Notification.id.desc())
        .limit(limit + 1)
    )
    notifications = result.scalars().all()
    has_more = len(notifications) > limit
    notifications = notifications[:limit]
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    notifications = [
        notification
        for notification in notifications
        if notification.actor_user_id not in blocked_user_ids
        and (notification.post is None or notification.post.user_id not in blocked_user_ids)
        and (notification.source_post is None or notification.source_post.user_id not in blocked_user_ids)
    ]

    await annotate_notification_posts(db, notifications, current_user.id)
    return NotificationListResponse(
        notifications=[notification_to_read(notification, current_user.id) for notification in notifications],
        total=total,
        next_cursor=notifications[-1].id if has_more and notifications else None,
        has_more=has_more,
    )


@router.post("/read-all", response_model=dict)
async def mark_all_notifications_read(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _notification_read_all_policies(current_user.id))

    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    )
    notifications = result.scalars().all()
    timestamp = await mark_notifications_read(db, notifications)
    await db.commit()
    return {"marked_count": len(notifications), "read_at": timestamp}


@router.post("/{notification_id}/read", response_model=NotificationMarkReadResponse)
async def mark_notification_read(
    request: Request,
    notification_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _notification_read_policies(current_user.id))

    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    timestamp = await mark_notifications_read(db, [notification])
    await db.commit()
    return NotificationMarkReadResponse(id=notification.id, read_at=timestamp)


@router.get("/settings", response_model=NotificationSettingsRead)
async def get_notification_settings(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_notification_settings(db, current_user.id)
    await db.commit()
    return NotificationSettingsRead.model_validate(settings)


@router.patch("/settings", response_model=NotificationSettingsRead)
async def update_notification_settings(
    request: Request,
    payload: NotificationSettingsUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _notification_settings_update_policies(current_user.id))
    settings = await get_or_create_notification_settings(db, current_user.id)
    for field_name in payload.model_fields_set:
        setattr(settings, field_name, getattr(payload, field_name))
    await db.commit()
    await db.refresh(settings)
    return NotificationSettingsRead.model_validate(settings)


@router.get("/push-subscriptions", response_model=PushSubscriptionListResponse)
async def get_push_subscriptions(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _push_subscription_read_policies(current_user.id))
    subscriptions = await list_push_subscriptions(db, user_id=current_user.id, include_inactive=True)
    return PushSubscriptionListResponse(
        subscriptions=subscriptions,
        push_configured=settings.web_push_enabled,
        vapid_public_key=settings.VAPID_PUBLIC_KEY or None,
    )


@router.put("/push-subscriptions", response_model=PushSubscriptionUpsertResponse)
async def put_push_subscription(
    request: Request,
    payload: PushSubscriptionUpsertRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _push_subscription_write_policies(current_user.id))
    subscription = await upsert_push_subscription(
        db,
        user_id=current_user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=payload.user_agent,
    )
    await db.commit()
    await db.refresh(subscription)
    return PushSubscriptionUpsertResponse(subscription=subscription)


@router.delete("/push-subscriptions", response_model=PushSubscriptionDeleteResponse)
async def remove_push_subscription(
    request: Request,
    payload: PushSubscriptionDeleteRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _push_subscription_write_policies(current_user.id))
    deleted_count = await delete_push_subscription(db, user_id=current_user.id, endpoint=payload.endpoint)
    await db.commit()
    return PushSubscriptionDeleteResponse(deleted_count=deleted_count)


@router.post("/push-subscriptions/test-send", response_model=PushTestSendResponse)
async def test_send_push(
    request: Request,
    payload: PushTestSendRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _push_test_send_policies(current_user.id))
    active_subscriptions = await list_push_subscriptions(db, user_id=current_user.id, include_inactive=False)
    result = await send_push_payload_to_user(
        db,
        user_id=current_user.id,
        payload={
            "title": payload.title or "Test push",
            "body": payload.body or "Push delivery is working.",
            "message": payload.body or "Push delivery is working.",
            "url": payload.url or "/notifications",
            "tag": "push-test",
            "notification_type": "test",
            "icon": "/icon-192.png",
            "badge": "/icon-192.png",
        },
    )
    await db.commit()
    return PushTestSendResponse(
        sent_count=result.sent_count,
        failed_count=result.failed_count,
        total_active=len(active_subscriptions),
    )
