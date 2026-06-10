from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bookmark import Bookmark
from app.models.like import Like
from app.models.post import Post, PostModerationStatus
from app.models.user import User, UserStatus
from app.schemas.post import PostRead
from app.schemas.user import InviterRead, UserPublicRead


def post_query_options():
    return (
        selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.author).selectinload(User.staff_permission),
        selectinload(Post.repost_of).selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.repost_of).selectinload(Post.author).selectinload(User.staff_permission),
        selectinload(Post.parent).selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.parent).selectinload(Post.author).selectinload(User.staff_permission),
        selectinload(Post.quoted_post).selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.quoted_post).selectinload(Post.author).selectinload(User.staff_permission),
        selectinload(Post.quoted_post).selectinload(Post.repost_of).selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.quoted_post).selectinload(Post.repost_of).selectinload(Post.author).selectinload(User.staff_permission),
        selectinload(Post.quoted_post).selectinload(Post.parent).selectinload(Post.author).selectinload(User.inviter),
        selectinload(Post.quoted_post).selectinload(Post.parent).selectinload(Post.author).selectinload(User.staff_permission),
    )


def visible_post_filter():
    return and_(
        Post.moderation_status == PostModerationStatus.VISIBLE,
        Post.author.has(User.is_active == True),
        Post.author.has(User.status == UserStatus.ACTIVE),
    )


def _user_to_read(user) -> UserPublicRead:
    return UserPublicRead(
        id=user.id,
        username=user.username,
        display_name=getattr(user, "display_name", None),
        avatar_url=user.avatar_url,
        cover_url=getattr(user, "cover_url", None),
        bio=user.bio,
        location=getattr(user, "location", None),
        website=getattr(user, "website", None),
        created_at=user.created_at,
        inviter=(
            InviterRead(
                id=user.inviter.id,
                username=user.inviter.username,
                display_name=getattr(user.inviter, "display_name", None),
                avatar_url=getattr(user.inviter, "avatar_url", None),
            )
            if getattr(user, "inviter", None)
            else None
        ),
    )


def get_canonical_post_id(post: Post) -> int:
    return post.repost_of_id or post.id


def get_display_post(post: Post) -> Post:
    return post.repost_of or post


def is_post_visible_to_viewer(post: Post | None) -> bool:
    if not post or not post.author:
        return False
    author_status = getattr(post.author, "status", UserStatus.ACTIVE)
    if isinstance(author_status, str):
        author_status = UserStatus(author_status)
    return (
        post.moderation_status == PostModerationStatus.VISIBLE
        and post.author.is_active is True
        and author_status == UserStatus.ACTIVE
    )


def post_to_read_schema(
    post: Post,
    current_user_id: Optional[int] = None,
    *,
    blocked_user_ids: set[int] | None = None,
    include_original: bool = True,
    include_parent: bool = True,
    include_quoted: bool = True,
) -> PostRead:
    blocked_user_ids = blocked_user_ids or set()
    original_post = None
    if include_original and post.repost_of and post.repost_of.author and post.repost_of.user_id not in blocked_user_ids:
        original_post = post_to_read_schema(
            post.repost_of,
            current_user_id,
            blocked_user_ids=blocked_user_ids,
            include_original=False,
            include_parent=True,
            include_quoted=True,
        )

    parent_post = None
    if include_parent and post.parent_id is not None and is_post_visible_to_viewer(post.parent) and post.parent.user_id not in blocked_user_ids:
        parent_post = post_to_read_schema(
            post.parent,
            current_user_id,
            blocked_user_ids=blocked_user_ids,
            include_original=True,
            include_parent=False,
            include_quoted=True,
        )

    quoted_post = None
    quoted_post_unavailable = False
    quoted_post_placeholder = None
    if include_quoted and post.quoted_post_id is not None:
        if is_post_visible_to_viewer(post.quoted_post) and post.quoted_post and post.quoted_post.user_id not in blocked_user_ids:
            quoted_post = post_to_read_schema(
                post.quoted_post,
                current_user_id,
                blocked_user_ids=blocked_user_ids,
                include_original=True,
                include_parent=True,
                include_quoted=False,
            )
        else:
            quoted_post_unavailable = True
            quoted_post_placeholder = "This quoted post is no longer available."

    return PostRead(
        id=post.id,
        user_id=post.user_id,
        content=post.content or "",
        media_url=post.media_url,
        parent_id=post.parent_id,
        repost_of_id=post.repost_of_id,
        quoted_post_id=post.quoted_post_id,
        is_repost=post.is_repost,
        is_quote=post.quoted_post_id is not None,
        likes_count=post.likes_count,
        replies_count=post.replies_count,
        reposts_count=post.reposts_count,
        created_at=post.created_at,
        is_liked_by_me=getattr(post, "is_liked_by_me", False),
        is_bookmarked=getattr(post, "is_bookmarked", getattr(post, "is_bookmarked_by_me", False)),
        is_bookmarked_by_me=getattr(post, "is_bookmarked_by_me", getattr(post, "is_bookmarked", False)),
        has_reposted=getattr(post, "has_reposted", False),
        moderation_status=post.moderation_status,
        moderation_reason=post.moderation_reason,
        moderated_at=post.moderated_at,
        moderated_by_user_id=post.moderated_by_user_id,
        author=_user_to_read(post.author),
        original_post=original_post,
        parent_post=parent_post,
        quoted_post=quoted_post,
        quoted_post_unavailable=quoted_post_unavailable,
        quoted_post_placeholder=quoted_post_placeholder,
    )


async def annotate_posts_for_user(db: AsyncSession, posts: Sequence[Post], current_user_id: Optional[int]) -> None:
    if not posts or not current_user_id:
        return

    all_posts_by_id: dict[int, Post] = {}
    for post in posts:
        all_posts_by_id[post.id] = post
        if post.repost_of:
            all_posts_by_id[post.repost_of.id] = post.repost_of
        if post.quoted_post:
            all_posts_by_id[post.quoted_post.id] = post.quoted_post

    post_ids = list(all_posts_by_id.keys())

    liked_result = await db.execute(
        select(Like.post_id).where(Like.user_id == current_user_id, Like.post_id.in_(post_ids))
    )
    liked_post_ids = set(liked_result.scalars().all())

    bookmarked_result = await db.execute(
        select(Bookmark.post_id).where(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids))
    )
    bookmarked_post_ids = set(bookmarked_result.scalars().all())

    reposted_result = await db.execute(
        select(Post.repost_of_id).where(
            Post.user_id == current_user_id,
            Post.is_repost == True,
            Post.repost_of_id.in_(post_ids),
        )
    )
    reposted_post_ids = {post_id for post_id in reposted_result.scalars().all() if post_id is not None}

    for post_id, post in all_posts_by_id.items():
        post.is_liked_by_me = post_id in liked_post_ids
        post.is_bookmarked = post_id in bookmarked_post_ids
        post.is_bookmarked_by_me = post.is_bookmarked
        post.has_reposted = post_id in reposted_post_ids


async def get_post_with_relations(
    db: AsyncSession,
    post_id: int,
    current_user_id: Optional[int] = None,
    include_moderated: bool = False,
) -> Optional[Post]:
    query = select(Post).options(*post_query_options()).where(Post.id == post_id)
    if not include_moderated:
        query = query.where(visible_post_filter())
    result = await db.execute(query)
    post = result.scalar_one_or_none()
    if post and current_user_id:
        await annotate_posts_for_user(db, [post], current_user_id)
    return post


async def collect_post_closure_ids(db: AsyncSession, root_post_id: int) -> set[int]:
    delete_ids = {root_post_id}
    frontier = {root_post_id}

    while frontier:
        result = await db.execute(
        select(Post.id)
            .where((Post.parent_id.in_(frontier)) | (Post.repost_of_id.in_(frontier)))
        )
        next_ids = {post_id for post_id in result.scalars().all() if post_id not in delete_ids}
        delete_ids.update(next_ids)
        frontier = next_ids

    return delete_ids


async def refresh_post_counts(db: AsyncSession, post_ids: Iterable[int]) -> None:
    post_ids = {post_id for post_id in post_ids if post_id is not None}
    if not post_ids:
        return

    posts_result = await db.execute(select(Post).where(Post.id.in_(post_ids)))
    posts = {post.id: post for post in posts_result.scalars().all()}
    if not posts:
        return

    replies_result = await db.execute(
        select(Post.parent_id, func.count(Post.id))
        .where(Post.parent_id.in_(posts.keys()), visible_post_filter())
        .group_by(Post.parent_id)
    )
    replies_map = {parent_id: count for parent_id, count in replies_result.all() if parent_id is not None}

    reposts_result = await db.execute(
        select(Post.repost_of_id, func.count(Post.id))
        .where(Post.repost_of_id.in_(posts.keys()), Post.is_repost == True, visible_post_filter())
        .group_by(Post.repost_of_id)
    )
    reposts_map = {repost_of_id: count for repost_of_id, count in reposts_result.all() if repost_of_id is not None}

    for post_id, post in posts.items():
        post.replies_count = replies_map.get(post_id, 0)
        post.reposts_count = reposts_map.get(post_id, 0)


async def delete_post_closure(db: AsyncSession, root_post: Post, *, actor_user_id: int | None = None, reason: str | None = None) -> dict:
    delete_ids = await collect_post_closure_ids(db, root_post.id)

    result = await db.execute(select(Post).options(*post_query_options()).where(Post.id.in_(delete_ids)))
    posts_to_delete = result.scalars().all()

    affected_post_ids = {
        reference_id
        for post in posts_to_delete
        for reference_id in (post.parent_id, post.repost_of_id)
        if reference_id is not None and reference_id not in delete_ids
    }

    summary = {
        "root_post_id": root_post.id,
        "deleted_post_ids": sorted(delete_ids),
        "deleted_count": len(delete_ids),
        "deleted_reply_ids": sorted(post.id for post in posts_to_delete if post.parent_id is not None),
        "deleted_repost_ids": sorted(post.id for post in posts_to_delete if post.is_repost),
    }

    for post in posts_to_delete:
        post.moderation_status = PostModerationStatus.DELETED
        post.moderation_reason = reason
        post.moderated_at = datetime.now(timezone.utc)
        post.moderated_by_user_id = actor_user_id

    await db.flush()
    await refresh_post_counts(db, affected_post_ids)

    return summary
