from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits
from app.models.moderation_signal import ModerationSurface
from app.models.user import User, UserStatus
from app.models.dm import DirectMessage
from app.api.deps import get_current_interactive_user, get_current_user
from app.services.blocks import (
    filter_blocked_users,
    get_block_relationship,
    get_blocked_user_ids,
    raise_blocked_conversation_error,
    raise_blocked_interaction_error,
)
from app.services.moderation_intake import (
    assess_text_content,
    create_moderation_signal,
    raise_blocked_content_error,
)

router = APIRouter(tags=["dm"])


def _dm_send_policies(sender_id: int, receiver_username: str) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="dm-send-burst",
            limit=4,
            window_seconds=60,
            key=build_scope_key("dm", "send", "burst", sender_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="dm-send-sustained",
            limit=25,
            window_seconds=3600,
            key=build_scope_key("dm", "send", "sustained", sender_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="dm-send-recipient",
            limit=12,
            window_seconds=600,
            key=build_scope_key("dm", "send", "recipient", sender_id, receiver_username.lower()),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


# Pydantic schemas
class MessageCreate(BaseModel):
    content: str = Field(..., max_length=2000)


class MessageResponse(BaseModel):
    id: int
    content: str
    created_at: datetime
    sender_id: int
    receiver_id: int
    is_read: bool

    class Config:
        from_attributes = True


class SenderResponse(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None

    class Config:
        from_attributes = True


class MessageWithSender(BaseModel):
    id: int
    content: str
    created_at: datetime
    sender: SenderResponse

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    user: SenderResponse
    last_message: Optional[str] = None
    unread_count: int = 0
    updated_at: Optional[datetime] = None


def _build_sender_response(user: User) -> SenderResponse:
    return SenderResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )


def _normalize_message_content(content: str) -> str:
    normalized_content = content.strip()
    if not normalized_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty.",
        )
    return normalized_content


def _enforce_dm_target_available(user: User) -> None:
    if user.status == UserStatus.BANNED or user.status == UserStatus.SUSPENDED or user.status == UserStatus.FROZEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account can't receive messages right now.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account can't receive messages right now.",
        )


class SendMessageResponse(BaseModel):
    id: int
    content: str
    created_at: datetime
    sender: SenderResponse

    class Config:
        from_attributes = True


class MessagesListResponse(BaseModel):
    messages: List[MessageWithSender]
    total: int
    has_more: bool


@router.get("/conversations", response_model=List[ConversationResponse])
async def get_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all conversations for the current user.
    Returns a list of users the current user has exchanged messages with,
    along with the last message and unread count.
    """
    # Get all unique users the current user has messaged with
    # Either as sender or receiver
    sent_subquery = (
        select(DirectMessage.receiver_id)
        .where(DirectMessage.sender_id == current_user.id)
        .distinct()
    )
    
    received_subquery = (
        select(DirectMessage.sender_id)
        .where(DirectMessage.receiver_id == current_user.id)
        .distinct()
    )
    
    # Get all unique user IDs
    result = await db.execute(
        select(User)
        .where(
            or_(
                User.id.in_(sent_subquery),
                User.id.in_(received_subquery)
            )
        )
    )
    conversation_users = result.scalars().all()
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    conversation_users = filter_blocked_users(conversation_users, blocked_user_ids)
    
    conversations = []
    
    for conversation_user in conversation_users:
        user_id = conversation_user.id
        # Get the last message between current user and this user
        last_msg_result = await db.execute(
            select(DirectMessage)
            .where(
                or_(
                    and_(DirectMessage.sender_id == current_user.id, DirectMessage.receiver_id == user_id),
                    and_(DirectMessage.sender_id == user_id, DirectMessage.receiver_id == current_user.id)
                )
            )
            .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()
        
        # Get unread count (messages sent to current user that are unread)
        unread_result = await db.execute(
            select(func.count(DirectMessage.id))
            .where(
                and_(
                    DirectMessage.sender_id == user_id,
                    DirectMessage.receiver_id == current_user.id,
                    DirectMessage.is_read == False
                )
            )
        )
        unread_count = unread_result.scalar() or 0
        
        conversations.append(ConversationResponse(
            user=_build_sender_response(conversation_user),
            last_message=last_msg.content if last_msg else None,
            unread_count=unread_count,
            updated_at=last_msg.created_at if last_msg else None
        ))
    
    # Sort by updated_at descending
    conversations.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
    
    return conversations


@router.post("/conversations/{username}", response_model=SendMessageResponse)
async def send_message(
    request: Request,
    username: str,
    message: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_interactive_user)
):
    """
    Send a message to a user by username.
    """
    await enforce_rate_limits(request, _dm_send_policies(current_user.id, username))

    # Find the receiver
    result = await db.execute(
        select(User).where(User.username == username)
    )
    receiver = result.scalar_one_or_none()
    
    if not receiver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if receiver.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send message to yourself"
        )

    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=receiver.id)).is_blocked:
        raise_blocked_interaction_error()

    _enforce_dm_target_available(receiver)
    normalized_content = _normalize_message_content(message.content)

    assessment = assess_text_content(ModerationSurface.DM_TEXT, normalized_content)
    if assessment.is_blocked:
        await create_moderation_signal(db, user_id=current_user.id, assessment=assessment)
        await db.commit()
        raise_blocked_content_error(assessment.surface_type)
    
    # Create the message
    db_message = DirectMessage(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        content=normalized_content
    )
    db.add(db_message)
    await db.flush()
    await create_moderation_signal(
        db,
        user_id=current_user.id,
        assessment=assessment,
        dm_message_id=db_message.id,
    )
    await db.commit()
    await db.refresh(db_message)
    
    return SendMessageResponse(
        id=db_message.id,
        content=db_message.content,
        created_at=db_message.created_at,
        sender=_build_sender_response(current_user)
    )


@router.post("/{username}", response_model=SendMessageResponse)
async def send_message_legacy(
    request: Request,
    username: str,
    message: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_interactive_user)
):
    """Backward-compatible alias for sending a message by username."""
    return await send_message(request=request, username=username, message=message, db=db, current_user=current_user)


@router.get("/conversations/{username}/messages", response_model=MessagesListResponse)
async def get_messages(
    username: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get messages with a specific user.
    Also marks all messages from that user as read.
    
    - Requires authentication
    - Only the sender or receiver can access the conversation
    """
    # Find the other user
    result = await db.execute(
        select(User).where(User.username == username)
    )
    other_user = result.scalar_one_or_none()
    
    if not other_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=other_user.id)).is_blocked:
        raise_blocked_conversation_error()
    
    # Get total count
    count_result = await db.execute(
        select(func.count(DirectMessage.id))
        .where(
            or_(
                and_(DirectMessage.sender_id == current_user.id, DirectMessage.receiver_id == other_user.id),
                and_(DirectMessage.sender_id == other_user.id, DirectMessage.receiver_id == current_user.id)
            )
        )
    )
    total = count_result.scalar() or 0
    
    # Calculate offset
    offset = (page - 1) * limit
    has_more = offset + limit < total
    
    # Get messages
    messages_result = await db.execute(
        select(DirectMessage)
        .options(selectinload(DirectMessage.sender))
        .where(
            or_(
                and_(DirectMessage.sender_id == current_user.id, DirectMessage.receiver_id == other_user.id),
                and_(DirectMessage.sender_id == other_user.id, DirectMessage.receiver_id == current_user.id)
            )
        )
        .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
        .offset(offset)
        .limit(limit)
    )
    messages = messages_result.scalars().all()
    
    # Mark messages from other user as read
    await db.execute(
        DirectMessage.__table__.update()
        .where(
            and_(
                DirectMessage.sender_id == other_user.id,
                DirectMessage.receiver_id == current_user.id,
                DirectMessage.is_read == False
            )
        )
        .values(is_read=True)
    )
    await db.commit()
    
    # Reverse to show oldest first
    messages = list(reversed(messages))
    
    return MessagesListResponse(
        messages=[
            MessageWithSender(
                id=msg.id,
                content=msg.content,
                created_at=msg.created_at,
                sender=_build_sender_response(msg.sender)
            )
            for msg in messages
        ],
        total=total,
        has_more=has_more
    )


@router.get("/{username}", response_model=MessagesListResponse)
async def get_messages_legacy(
    username: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """[DEPRECATED] Backward-compatible alias for loading messages by username.

    This route exists for legacy clients that used the /dm/{username} path directly.
    The canonical endpoint is GET /dm/conversations/{username}/messages.
    This legacy path is not used by the current frontend and may be removed in a future version.
    """
    return await get_messages(username=username, page=page, limit=limit, db=db, current_user=current_user)
