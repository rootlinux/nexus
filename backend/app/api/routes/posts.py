import ipaddress
import socket
from typing import Literal, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_ERROR, RateLimitPolicy, build_scope_key, enforce_rate_limits, get_client_ip, hash_key_part
from app.models.moderation_signal import ModerationDetectionStatus, ModerationReviewStatus, ModerationSignal, ModerationSurface
from app.models.user import User
from app.models.post import Post
from app.models.like import Like
from app.models.bookmark import Bookmark
from app.schemas.post import (
    BookmarkResponse,
    DiscoveryFeedResponse,
    FeedResponse,
    LikeResponse,
    PostCreate,
    PostList,
    PostRead,
    ReplyCreate,
    ReplyResponse,
    RepostResponse,
)
from app.api.deps import get_current_interactive_user, get_current_user, get_optional_user
from app.storage import get_storage_provider
from app.services.blocks import get_block_relationship, get_blocked_user_ids, raise_blocked_interaction_error
from app.services.discovery import TRENDING_WINDOW_HOURS, build_discovery_feed, build_trending_feed
from app.services.feed_ranking import build_home_feed
from app.services.moderation_intake import (
    assess_media_input,
    assess_media_url,
    assess_text_content,
    create_moderation_signal,
    find_signal_by_media_url,
    raise_blocked_content_error,
    raise_review_required_error,
)
from app.services.notifications import (
    create_like_notification,
    create_mention_notifications,
    create_quote_notification,
    create_reply_notifications,
    create_repost_notification,
)
from app.services.post_views import (
    annotate_posts_for_user,
    delete_post_closure,
    get_post_with_relations,
    post_query_options,
    post_to_read_schema,
    refresh_post_counts,
    visible_post_filter,
)

_SSRF_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_allowed_local_media_url(url: str) -> bool:
    normalized = (url or "").strip()
    if not normalized:
        return False

    upload_prefix = settings.LOCAL_UPLOAD_URL_PREFIX.rstrip("/") or "/uploads"
    return normalized == upload_prefix or normalized.startswith(f"{upload_prefix}/")


def _validate_media_url_no_ssrf(url: str) -> None:
    """Reject media URLs that point at private/internal network addresses."""
    if _is_allowed_local_media_url(url):
        return

    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media URL")

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media URL must use http or https")

    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media URL")

    # Block reserved hostnames before DNS resolution
    lower_host = hostname.lower()
    if lower_host in {"localhost", "127.0.0.1", "::1"} or lower_host.endswith(".local") or lower_host.endswith(".internal"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media URL not allowed")

    # Resolve hostname and check against private ranges
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except OSError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media URL hostname could not be resolved")

    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for blocked in _SSRF_BLOCKED_NETWORKS:
            if ip in blocked:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media URL not allowed")


router = APIRouter(tags=["posts"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _normalize_repost_target(post: Post) -> Post:
    return post.repost_of or post


def _post_mutation_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-create-burst",
            limit=3,
            window_seconds=30,
            key=build_scope_key("post", "create", "burst", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="post-create-sustained",
            limit=12,
            window_seconds=600,
            key=build_scope_key("post", "create", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _reply_mutation_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="reply-create-burst",
            limit=3,
            window_seconds=30,
            key=build_scope_key("reply", "create", "burst", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="reply-create-sustained",
            limit=10,
            window_seconds=600,
            key=build_scope_key("reply", "create", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _repost_mutation_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="repost-toggle-burst",
            limit=4,
            window_seconds=30,
            key=build_scope_key("repost", "toggle", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name="repost-toggle-sustained",
            limit=15,
            window_seconds=600,
            key=build_scope_key("repost", "toggle", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _bookmark_mutation_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="bookmark-toggle",
            limit=40,
            window_seconds=600,
            key=build_scope_key("bookmark", "toggle", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _like_toggle_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="like-toggle-burst",
            limit=12,
            window_seconds=60,
            key=build_scope_key("like", "toggle", "burst", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="like-toggle-sustained",
            limit=90,
            window_seconds=3600,
            key=build_scope_key("like", "toggle", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _like_toggle_target_policies(user_id: int, post_id: int, target_user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="like-toggle-post-hammer",
            limit=4,
            window_seconds=60,
            key=build_scope_key("like", "toggle", "post", user_id, post_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
        RateLimitPolicy(
            name="like-toggle-target-user",
            limit=10,
            window_seconds=300,
            key=build_scope_key("like", "toggle", "target-user", user_id, target_user_id),
            message=RATE_LIMIT_ERROR,
            strategy="sliding_window",
            require_redis_in_production=True,
        ),
    ]


def _feed_read_policies(scope_key: str, *, authenticated: bool = True) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="feed-read",
            limit=30 if authenticated else 20,
            window_seconds=60,
            key=scope_key,
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _post_detail_policies(scope_key: str, *, authenticated: bool = False) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-detail-read",
            limit=60 if authenticated else 30,
            window_seconds=60,
            key=scope_key,
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _post_replies_policies(scope_key: str, *, authenticated: bool = False) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-replies-read",
            limit=60 if authenticated else 30,
            window_seconds=60,
            key=scope_key,
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _read_scope_key(request: Request, current_user: Optional[User], prefix: str) -> str:
    if current_user:
        return build_scope_key(prefix, "user", current_user.id)
    return build_scope_key(prefix, "ip", hash_key_part(get_client_ip(request)))


def _media_upload_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-media-upload-burst",
            limit=4,
            window_seconds=60,
            key=build_scope_key("post", "media", "burst", user_id),
            message=RATE_LIMIT_ERROR,
        ),
        RateLimitPolicy(
            name="post-media-upload-sustained",
            limit=15,
            window_seconds=3600,
            key=build_scope_key("post", "media", "sustained", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _post_delete_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-delete",
            limit=20,
            window_seconds=60,
            key=build_scope_key("post", "delete", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


def _post_report_policies(user_id: int) -> list[RateLimitPolicy]:
    return [
        RateLimitPolicy(
            name="post-report",
            limit=10,
            window_seconds=3600,
            key=build_scope_key("post", "report", user_id),
            message=RATE_LIMIT_ERROR,
        ),
    ]


@router.post("/{post_id}/report")
async def report_post(
    request: Request,
    post_id: int,
    body: dict,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Report a post for moderation review.
    
    - Requires authentication
    - Only non-owners can report posts
    - Body: { reason: string } - optional short reason
    - Creates a ModerationSignal with source='user_report', risk_score=50, status=OPEN
    - Returns 200 if already reported (idempotent)
    - Rate limited to 10 reports per hour per user
    """
    await enforce_rate_limits(request, _post_report_policies(current_user.id))

    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    
    if post.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot report your own post"
        )

    reason = body.get("reason") if body else None
    reason_codes = ["user_report"]
    if reason:
        reason_codes.append(reason)

    existing_signal_result = await db.execute(
        select(ModerationSignal).where(
            ModerationSignal.post_id == post_id,
            ModerationSignal.user_id == current_user.id,
        )
    )
    existing_signal = existing_signal_result.scalar_one_or_none()
    if existing_signal:
        return {"message": "Report already submitted", "signal_id": existing_signal.id}

    surface_type = ModerationSurface.POST_TEXT if post.content else ModerationSurface.POST_MEDIA
    content_preview = (post.content or "")[:500] if post.content else None

    signal = ModerationSignal(
        user_id=current_user.id,
        post_id=post_id,
        surface_type=surface_type,
        detection_status=ModerationDetectionStatus.SUSPICIOUS,
        review_status=ModerationReviewStatus.OPEN,
        reason_codes=reason_codes,
        reason_summary=reason or "user_report",
        risk_score=50,
        content_preview=content_preview,
    )
    db.add(signal)
    await db.commit()
    await db.refresh(signal)

    return {"message": "Report submitted", "signal_id": signal.id}


@router.post("/upload-image", status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an image for a post.
    
    - Requires authentication
    - Max file size: 5MB
    - Allowed types: JPEG, PNG, GIF, WebP
    - SVG and other unsafe formats are explicitly blocked
    """
    await enforce_rate_limits(request, _media_upload_policies(current_user.id))

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file"
        ) from exc

    assessment = assess_media_input(
        ModerationSurface.POST_MEDIA,
        content_type=file.content_type,
        original_filename=file.filename,
        content=content,
        content_size=len(content),
        max_size=MAX_FILE_SIZE,
    )
    signal = await create_moderation_signal(db, user_id=current_user.id, assessment=assessment)
    if assessment.is_blocked:
        await db.commit()
        raise_blocked_content_error(assessment.surface_type)

    if assessment.requires_review:
        await db.commit()
        raise_review_required_error(assessment.surface_type)

    storage_provider = get_storage_provider()

    # Save file only after moderation passes so review-required uploads never become public.
    try:
        stored_media = await storage_provider.save_file(
            content=content,
            content_type=assessment.canonical_content_type or file.content_type or "image/jpeg",
            original_filename=file.filename,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file"
        )

    assessment.media_url = stored_media.public_url
    signal.media_url = stored_media.public_url
    await db.commit()
    return {"url": stored_media.public_url}

@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def create_post(
    request: Request,
    post_data: PostCreate,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new post.
    
    - Requires authentication
    - Content must be 280 characters or less
    - Can reply to existing post (parent_id)
    - Can repost existing post (repost_of_id)
    - Can quote an existing post (quoted_post_id)
    """
    await enforce_rate_limits(request, _post_mutation_policies(current_user.id))

    normalized_content = (post_data.content or "").strip()
    media_url = (post_data.media_url or "").strip() or None
    has_media = bool(media_url)
    is_repost_request = post_data.repost_of_id is not None
    is_quote_request = post_data.quoted_post_id is not None

    if post_data.parent_id and is_quote_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A post cannot be both a reply and a quote",
        )

    if is_repost_request and (normalized_content or has_media or post_data.parent_id or is_quote_request):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reposts cannot include commentary, media, replies, or quoted posts",
        )

    if not normalized_content and not has_media and not is_repost_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post must include text or media",
        )

    text_assessment = assess_text_content(ModerationSurface.POST_TEXT, normalized_content)
    text_signal = await create_moderation_signal(db, user_id=current_user.id, assessment=text_assessment)
    if text_assessment.is_blocked:
        await db.commit()
        raise_blocked_content_error(text_assessment.surface_type)

    media_signal: ModerationSignal | None = None
    if media_url:
        _validate_media_url_no_ssrf(media_url)
        media_signal = await find_signal_by_media_url(
            db,
            user_id=current_user.id,
            surface_type=ModerationSurface.POST_MEDIA,
            media_url=media_url,
        )
        if media_signal is None:
            media_assessment = assess_media_url(ModerationSurface.POST_MEDIA, media_url)
            media_signal = await create_moderation_signal(db, user_id=current_user.id, assessment=media_assessment)
        if media_signal.detection_status.value == "blocked":
            await db.commit()
            raise_blocked_content_error(ModerationSurface.POST_MEDIA)
        if media_signal.detection_status.value == "suspicious":
            await db.commit()
            raise_review_required_error(ModerationSurface.POST_MEDIA)
    
    # Check if parent_id refers to valid post
    if post_data.parent_id:
        result = await db.execute(
            select(Post).where(Post.id == post_data.parent_id, visible_post_filter())
        )
        parent_post = result.scalar_one_or_none()
        if not parent_post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent post not found"
            )
        if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=parent_post.user_id)).is_blocked:
            raise_blocked_interaction_error()
    
    repost_target = None
    if is_repost_request:
        result = await db.execute(
            select(Post)
            .options(*post_query_options())
            .where(Post.id == post_data.repost_of_id, visible_post_filter())
        )
        repost_target = result.scalar_one_or_none()
        if not repost_target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repost target post not found"
            )
        if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=repost_target.user_id)).is_blocked:
            raise_blocked_interaction_error()
        repost_target = _normalize_repost_target(repost_target)

        repost_result = await db.execute(
            select(Post.id).where(
                Post.user_id == current_user.id,
                Post.is_repost == True,
                Post.repost_of_id == repost_target.id,
            )
        )
        if repost_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already reposted this post",
            )

    quoted_target = None
    if is_quote_request:
        result = await db.execute(
            select(Post)
            .options(*post_query_options())
            .where(Post.id == post_data.quoted_post_id, visible_post_filter())
        )
        quoted_target = result.scalar_one_or_none()
        if not quoted_target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quoted post not found"
            )
        if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=quoted_target.user_id)).is_blocked:
            raise_blocked_interaction_error()
        quoted_target = _normalize_repost_target(quoted_target)
    
    # Create new post
    new_post = Post(
        user_id=current_user.id,
        content=normalized_content,
        media_url=media_url,
        parent_id=post_data.parent_id,
        repost_of_id=repost_target.id if repost_target else None,
        quoted_post_id=quoted_target.id if quoted_target else None,
        is_repost=repost_target is not None
    )
    
    db.add(new_post)
    await db.flush()
    if text_signal.post_id is None:
        text_signal.post_id = new_post.id
    if media_signal and media_signal.post_id is None:
        media_signal.post_id = new_post.id
    if repost_target:
        await refresh_post_counts(db, [repost_target.id])
        await create_repost_notification(db, actor_user_id=current_user.id, target_post=repost_target)
    if quoted_target:
        await create_quote_notification(db, actor_user_id=current_user.id, target_post=quoted_target, quote_post=new_post)
    if post_data.parent_id:
        await refresh_post_counts(db, [post_data.parent_id])
        parent_result = await db.execute(select(Post).where(Post.id == post_data.parent_id))
        parent_post = parent_result.scalar_one()
        await create_reply_notifications(db, actor_user_id=current_user.id, parent_post=parent_post, reply_post=new_post)
    await create_mention_notifications(db, actor_user_id=current_user.id, source_post=new_post)
    await db.commit()
    await db.refresh(new_post)
    
    # Load author relationship
    result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.id == new_post.id)
    )
    new_post = result.scalar_one()
    
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    return post_to_read_schema(new_post, blocked_user_ids=blocked_user_ids)


@router.get("/{post_id:int}", response_model=PostRead)
async def get_post(
    request: Request,
    post_id: int,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a single post by ID.

    - Returns post with author information
    - Shows if current user has liked/bookmarked the post
    """
    await enforce_rate_limits(request, _post_detail_policies(_read_scope_key(request, current_user, "post:detail"), authenticated=current_user is not None))
    current_user_id = current_user.id if current_user else None
    post = await get_post_with_relations(db, post_id, current_user_id)
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    if current_user_id and post.user_id in blocked_user_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post_to_read_schema(post, current_user_id, blocked_user_ids=blocked_user_ids)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    request: Request,
    post_id: int,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a post.
    
    - Requires authentication
    - Only the post author can delete their own post
    """
    await enforce_rate_limits(request, _post_delete_policies(current_user.id))
    result = await db.execute(
        select(Post).options(*post_query_options()).where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own posts"
        )

    await delete_post_closure(db, post, actor_user_id=current_user.id, reason="Deleted by author")
    await db.commit()


@router.post("/{post_id}/like", response_model=LikeResponse)
async def toggle_like(
    request: Request,
    post_id: int,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle like on a post.
    
    - Requires authentication
    - If already liked, removes the like
    - If not liked, adds the like
    - Returns current like status and count
    """
    await enforce_rate_limits(request, _like_toggle_policies(current_user.id))

    # Check if post exists
    result = await db.execute(select(Post).where(Post.id == post_id, visible_post_filter()))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    if post.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot like your own post")
    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=post.user_id)).is_blocked:
        raise_blocked_interaction_error()

    await enforce_rate_limits(request, _like_toggle_target_policies(current_user.id, post.id, post.user_id))
    
    # Check if user already liked this post
    like_result = await db.execute(
        select(Like).where(
            Like.user_id == current_user.id,
            Like.post_id == post_id
        )
    )
    existing_like = like_result.scalar_one_or_none()
    
    if existing_like:
        # Remove like
        await db.delete(existing_like)
        post.likes_count = max(0, post.likes_count - 1)
        liked = False
    else:
        # Add like
        new_like = Like(
            user_id=current_user.id,
            post_id=post_id
        )
        db.add(new_like)
        post.likes_count += 1
        await db.flush()
        await create_like_notification(db, actor_user_id=current_user.id, target_post=post)
        liked = True
    
    await db.commit()
    await db.refresh(post)
    
    return LikeResponse(liked=liked, likes_count=post.likes_count)


@router.post("/{post_id}/repost", response_model=RepostResponse)
async def toggle_repost(
    request: Request,
    post_id: int,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle repost on a post.
    
    - Requires authentication
    - If already reposted, removes the repost
    - If not reposted, adds the repost
    - Returns current repost status and count
    """
    await enforce_rate_limits(request, _repost_mutation_policies(current_user.id))

    # Check if post exists
    result = await db.execute(select(Post).options(*post_query_options()).where(Post.id == post_id, visible_post_filter()))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=post.user_id)).is_blocked:
        raise_blocked_interaction_error()
    
    post = _normalize_repost_target(post)

    repost_result = await db.execute(
        select(Post).where(
            Post.repost_of_id == post.id,
            Post.user_id == current_user.id,
            Post.is_repost == True
        )
    )
    existing_repost = repost_result.scalar_one_or_none()
    
    if existing_repost:
        await db.delete(existing_repost)
        reposted = False
    else:
        new_repost = Post(
            user_id=current_user.id,
            content="",  # Reposts have empty content
            repost_of_id=post.id,
            is_repost=True
        )
        db.add(new_repost)
        await db.flush()
        await create_repost_notification(db, actor_user_id=current_user.id, target_post=post)
        reposted = True

    await db.flush()
    await refresh_post_counts(db, [post.id])
    await db.commit()
    await db.refresh(post)
    
    return RepostResponse(reposted=reposted, reposts_count=post.reposts_count)


@router.post("/{post_id}/bookmark", response_model=BookmarkResponse)
async def toggle_bookmark(
    request: Request,
    post_id: int,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle bookmark on a visible post for the current user.

    - Requires authentication
    - If bookmark exists, removes it
    - If bookmark does not exist, creates it
    - Returns current bookmark truth
    """
    await enforce_rate_limits(request, _bookmark_mutation_policies(current_user.id))

    result = await db.execute(
        select(Post).where(Post.id == post_id, visible_post_filter())
    )
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id if current_user else None)
    if current_user and post.user_id in blocked_user_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    bookmark_result = await db.execute(
        select(Bookmark).where(
            Bookmark.user_id == current_user.id,
            Bookmark.post_id == post_id,
        )
    )
    existing_bookmark = bookmark_result.scalar_one_or_none()

    if existing_bookmark:
        await db.delete(existing_bookmark)
        is_bookmarked = False
    else:
        db.add(
            Bookmark(
                user_id=current_user.id,
                post_id=post_id,
            )
        )
        is_bookmarked = True

    await db.commit()

    return BookmarkResponse(post_id=post_id, is_bookmarked=is_bookmarked)


@router.get("/{post_id}/replies", response_model=PostList)
async def get_post_replies(
    request: Request,
    post_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    order: Literal["asc", "desc"] = Query("desc"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get replies to a post.

    - Returns paginated list of replies
    - Sorted by created_at in the requested order
    """
    await enforce_rate_limits(request, _post_replies_policies(_read_scope_key(request, current_user, "post:replies"), authenticated=current_user is not None))
    # Check if post exists
    result = await db.execute(
        select(Post).where(Post.id == post_id, visible_post_filter())
    )
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    
    # Calculate skip from page
    skip = (page - 1) * limit
    
    # Get replies
    count_result = await db.execute(
        select(func.count())
        .select_from(Post)
        .where(Post.parent_id == post_id, visible_post_filter())
    )
    total = count_result.scalar()
    
    order_by = (Post.created_at.asc(), Post.id.asc()) if order == "asc" else (Post.created_at.desc(), Post.id.desc())

    result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.parent_id == post_id, visible_post_filter())
        .order_by(*order_by)
        .offset(skip)
        .limit(limit)
    )
    posts = result.scalars().all()
    
    current_user_id = current_user.id if current_user else None
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    posts = [p for p in posts if p.user_id not in blocked_user_ids]
    await annotate_posts_for_user(db, posts, current_user_id)
    posts_read = [post_to_read_schema(p, current_user_id, blocked_user_ids=blocked_user_ids) for p in posts]
    
    has_more = (page * limit) < total
    
    return PostList(posts=posts_read, total=total, page=page, limit=limit, has_more=has_more)


@router.post("/{post_id}/replies", response_model=ReplyResponse, status_code=status.HTTP_201_CREATED)
async def create_reply(
    request: Request,
    post_id: int,
    reply_data: ReplyCreate,
    current_user: User = Depends(get_current_interactive_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a reply to a post.
    
    - Requires authentication
    - Content must be 280 characters or less
    - Creates a post with parent_id = post_id
    - Refreshes replies_count from visible reply truth
    - Returns the created reply and updated count
    """
    await enforce_rate_limits(request, _reply_mutation_policies(current_user.id))

    # Check if parent post exists
    result = await db.execute(
        select(Post).where(Post.id == post_id, visible_post_filter())
    )
    parent_post = result.scalar_one_or_none()
    
    if not parent_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent post not found"
        )
    if (await get_block_relationship(db, current_user_id=current_user.id, target_user_id=parent_post.user_id)).is_blocked:
        raise_blocked_interaction_error()
    
    # Create the reply
    new_reply = Post(
        user_id=current_user.id,
        content=reply_data.content,
        parent_id=post_id
    )
    
    db.add(new_reply)
    
    await db.flush()
    await refresh_post_counts(db, [parent_post.id])
    await create_reply_notifications(db, actor_user_id=current_user.id, parent_post=parent_post, reply_post=new_reply)
    await create_mention_notifications(db, actor_user_id=current_user.id, source_post=new_reply)
    
    await db.commit()
    await db.refresh(new_reply)
    
    # Load author relationship
    result = await db.execute(
        select(Post)
        .options(*post_query_options())
        .where(Post.id == new_reply.id)
    )
    new_reply = result.scalar_one()
    
    return ReplyResponse(
        reply=post_to_read_schema(new_reply, current_user.id, blocked_user_ids=await get_blocked_user_ids(db, current_user.id)),
        replies_count=parent_post.replies_count
    )


@router.get("/feed", response_model=FeedResponse)
async def get_feed(
    request: Request,
    cursor: Optional[int] = Query(None, description="Feed cursor for pagination"),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the ranked home feed.

    - Requires authentication
    - Returns visible top-level posts only
    - Reuses moderation visibility truth
    - Prioritizes follows, network proximity, engagement, and freshness
    """
    await enforce_rate_limits(request, _feed_read_policies(build_scope_key("feed", "home", "user", current_user.id)))
    return await build_home_feed(
        db,
        current_user=current_user,
        cursor=cursor,
        limit=limit,
    )


@router.get("/explore", response_model=DiscoveryFeedResponse)
async def get_explore_feed(
    request: Request,
    mode: Literal["for_you", "trending"] = Query("for_you"),
    limit: int = Query(12, ge=1, le=30),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _feed_read_policies(_read_scope_key(request, current_user, "feed:explore"), authenticated=current_user is not None))
    current_user_id = current_user.id if current_user else None
    return await build_discovery_feed(
        db,
        mode=mode,
        current_user_id=current_user_id,
        limit=limit,
    )


@router.get("/trending", response_model=DiscoveryFeedResponse)
async def get_trending_posts(
    request: Request,
    limit: int = Query(5, ge=1, le=10),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limits(request, _feed_read_policies(_read_scope_key(request, current_user, "feed:trending"), authenticated=current_user is not None))
    current_user_id = current_user.id if current_user else None
    return await build_trending_feed(
        db,
        current_user_id=current_user_id,
        limit=limit,
        window_hours=TRENDING_WINDOW_HOURS,
    )
