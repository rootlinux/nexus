from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.service_auth import (
    SCOPE_DELETE,
    SCOPE_NOTIFY,
    SCOPE_READ,
    ServiceAuthContext,
    require_service_scope,
)
from app.core.database import get_db
from app.models.post import Post
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.services.audit import write_audit_log
from app.services.push_notifications import send_push_payload_to_user, web_push_is_configured

router = APIRouter(prefix="/admin/service", tags=["admin-service"])


class PushNotificationRequest(BaseModel):
    user_id: str = Field(..., description="Target user ID")
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=500)


class PushNotificationResponse(BaseModel):
    sent_count: int
    failed_count: int
    total_active_subscriptions: int


@router.get("/users")
async def list_users(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_READ)),
):
    result = await db.execute(
        select(User)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    users = result.scalars().all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "status": user.status.value,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        for user in users
    ]


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_READ)),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_DELETE)),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await db.delete(user)
    await write_audit_log(
        db,
        action="admin_service.delete_user",
        actor_type="service",
        service_principal_id=auth.principal_id,
        auth_scopes=sorted(auth.scopes),
        target_type="user",
        target_id=user_id,
        request=request,
    )
    await db.commit()
    return {"message": "User deleted", "user_id": user_id}


@router.get("/posts")
async def list_posts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Query(None, description="Filter by author user ID"),
    db: AsyncSession = Depends(get_db),
    _auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_READ)),
):
    query = select(Post).order_by(Post.created_at.desc()).offset(offset).limit(limit)
    if user_id is not None:
        query = query.where(Post.user_id == user_id)
    result = await db.execute(query)
    posts = result.scalars().all()
    return [
        {
            "id": post.id,
            "user_id": post.user_id,
            "content": post.content,
            "author_username": post.author.username if post.author else None,
            "created_at": post.created_at.isoformat() if post.created_at else None,
        }
        for post in posts
    ]


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_DELETE)),
):
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    await db.delete(post)
    await write_audit_log(
        db,
        action="admin_service.delete_post",
        actor_type="service",
        service_principal_id=auth.principal_id,
        auth_scopes=sorted(auth.scopes),
        target_type="post",
        target_id=post_id,
        request=request,
    )
    await db.commit()
    return {"message": "Post deleted", "post_id": post_id}


@router.post("/notifications/push", response_model=PushNotificationResponse)
async def send_push_notification(
    payload: PushNotificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_NOTIFY)),
):
    if not web_push_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web push is not configured on the server",
        )

    try:
        target_user_id = int(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user_id format")

    user_result = await db.execute(select(User).where(User.id == target_user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    subscriptions_result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == target_user_id,
            PushSubscription.is_active.is_(True),
        )
    )
    subscriptions = list(subscriptions_result.scalars().all())

    result = await send_push_payload_to_user(
        db,
        user_id=target_user_id,
        payload={
            "title": payload.title,
            "body": payload.body,
            "message": payload.body,
            "url": f"/{user.username}",
            "tag": f"admin-notif-{user.id}",
            "notification_type": "admin_message",
            "icon": "/icon-192.png",
            "badge": "/icon-192.png",
        },
    )
    await write_audit_log(
        db,
        action="admin_service.send_push_notification",
        actor_type="service",
        service_principal_id=auth.principal_id,
        auth_scopes=sorted(auth.scopes),
        target_type="user",
        target_id=target_user_id,
        after={
            "title": payload.title,
            "sent_count": result.sent_count,
            "failed_count": result.failed_count,
        },
        request=request,
    )
    await db.commit()

    return PushNotificationResponse(
        sent_count=result.sent_count,
        failed_count=result.failed_count,
        total_active_subscriptions=len(subscriptions),
    )


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _auth: ServiceAuthContext = Depends(require_service_scope(SCOPE_READ)),
):
    user_count_result = await db.execute(select(func.count(User.id)))
    user_count = int(user_count_result.scalar() or 0)

    post_count_result = await db.execute(select(func.count(Post.id)))
    post_count = int(post_count_result.scalar() or 0)

    return {
        "total_users": user_count,
        "total_posts": post_count,
    }
