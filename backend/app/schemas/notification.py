from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class NotificationActorRead(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationPostContextRead(BaseModel):
    id: Optional[int] = None
    content_snippet: Optional[str] = None
    author_username: Optional[str] = None
    author_display_name: Optional[str] = None
    is_quote: bool = False
    is_reply: bool = False
    is_available: bool = True
    unavailable_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationRead(BaseModel):
    id: int
    notification_type: NotificationType
    created_at: datetime
    read_at: Optional[datetime] = None
    is_unread: bool
    actor: NotificationActorRead
    post: Optional[NotificationPostContextRead] = None
    source_post: Optional[NotificationPostContextRead] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    notifications: list[NotificationRead]
    total: int
    next_cursor: Optional[int] = None
    has_more: bool


class NotificationMarkReadResponse(BaseModel):
    id: int
    read_at: datetime


class NotificationSettingsRead(BaseModel):
    push_likes: bool
    push_replies: bool
    push_reposts: bool
    push_mentions: bool
    push_follows: bool
    email_likes: bool
    email_replies: bool
    email_reposts: bool
    email_mentions: bool
    email_follows: bool

    model_config = ConfigDict(from_attributes=True)


class NotificationSettingsUpdate(BaseModel):
    push_likes: Optional[bool] = None
    push_replies: Optional[bool] = None
    push_reposts: Optional[bool] = None
    push_mentions: Optional[bool] = None
    push_follows: Optional[bool] = None
    email_likes: Optional[bool] = None
    email_replies: Optional[bool] = None
    email_reposts: Optional[bool] = None
    email_mentions: Optional[bool] = None
    email_follows: Optional[bool] = None


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionUpsertRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    user_agent: Optional[str] = None


class PushSubscriptionDeleteRequest(BaseModel):
    endpoint: str


class PushSubscriptionRead(BaseModel):
    id: int
    endpoint: str
    p256dh: str
    user_agent: Optional[str] = None
    last_seen_at: datetime
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PushSubscriptionListResponse(BaseModel):
    subscriptions: list[PushSubscriptionRead]
    push_configured: bool
    vapid_public_key: Optional[str] = None


class PushSubscriptionUpsertResponse(BaseModel):
    subscription: PushSubscriptionRead


class PushSubscriptionDeleteResponse(BaseModel):
    deleted_count: int


class PushTestSendRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    url: Optional[str] = None


class PushTestSendResponse(BaseModel):
    sent_count: int
    failed_count: int
    total_active: int
