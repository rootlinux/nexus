from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.like import Like
from app.models.post import Post
from app.models.user import User
from app.services.blocks import filter_blocked_posts, get_blocked_user_ids
from app.services.post_views import annotate_posts_for_user, post_query_options, post_to_read_schema, visible_post_filter

ProfileTimelineView = Literal["posts", "replies", "media", "likes", "reposts"]


def _authored_non_repost_filter(user_id: int):
    return (
        Post.user_id == user_id,
        Post.is_repost == False,
        Post.repost_of_id.is_(None),
        visible_post_filter(),
    )


def build_profile_posts_query(user_id: int, view: ProfileTimelineView) -> Select:
    base_query = select(Post).options(*post_query_options())

    if view == "posts":
        return base_query.where(
            *_authored_non_repost_filter(user_id),
            Post.parent_id.is_(None),
        )

    if view == "replies":
        return base_query.where(
            *_authored_non_repost_filter(user_id),
            Post.parent_id.is_not(None),
            Post.parent.has(visible_post_filter()),
        )

    if view == "media":
        return base_query.where(
            *_authored_non_repost_filter(user_id),
            Post.media_url.is_not(None),
            Post.media_url != "",
        )

    if view == "likes":
        return (
            base_query
            .join(Like, Like.post_id == Post.id)
            .where(Like.user_id == user_id, visible_post_filter())
            .order_by(Like.created_at.desc(), Post.id.desc())
        )

    return base_query.where(
        Post.user_id == user_id,
        Post.is_repost == True,
        Post.repost_of_id.is_not(None),
        visible_post_filter(),
        Post.repost_of.has(visible_post_filter()),
    )


def build_profile_posts_count_query(user_id: int, view: ProfileTimelineView):
    if view == "posts":
        return select(func.count()).select_from(Post).where(
            *_authored_non_repost_filter(user_id),
            Post.parent_id.is_(None),
        )

    if view == "replies":
        return select(func.count()).select_from(Post).where(
            *_authored_non_repost_filter(user_id),
            Post.parent_id.is_not(None),
            Post.parent.has(visible_post_filter()),
        )

    if view == "media":
        return select(func.count()).select_from(Post).where(
            *_authored_non_repost_filter(user_id),
            Post.media_url.is_not(None),
            Post.media_url != "",
        )

    if view == "likes":
        return (
            select(func.count())
            .select_from(Like)
            .join(Post, Post.id == Like.post_id)
            .where(Like.user_id == user_id, visible_post_filter())
        )

    return select(func.count()).select_from(Post).where(
        Post.user_id == user_id,
        Post.is_repost == True,
        Post.repost_of_id.is_not(None),
        visible_post_filter(),
        Post.repost_of.has(visible_post_filter()),
    )


async def get_profile_timeline(
    db: AsyncSession,
    *,
    user: User,
    view: ProfileTimelineView,
    skip: int,
    limit: int,
    current_user_id: Optional[int],
) -> dict:
    total_result = await db.execute(build_profile_posts_count_query(user.id, view))
    total = int(total_result.scalar() or 0)

    query = build_profile_posts_query(user.id, view)
    if view != "likes":
        query = query.order_by(Post.created_at.desc(), Post.id.desc())
    query = query.offset(skip).limit(limit)

    posts_result = await db.execute(query)
    posts = posts_result.scalars().all()
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    posts = filter_blocked_posts(posts, blocked_user_ids)

    await annotate_posts_for_user(db, posts, current_user_id)

    return {
        "posts": [post_to_read_schema(post, current_user_id, blocked_user_ids=blocked_user_ids) for post in posts],
        "total": total,
        "page": (skip // limit) + 1,
        "limit": limit,
        "has_more": (skip + limit) < total,
    }
