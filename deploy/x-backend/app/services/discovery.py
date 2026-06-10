from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.post import Post
from app.models.user import User, UserStatus
from app.schemas.post import (
    DiscoveryAuthorSummary,
    DiscoveryEngagement,
    DiscoveryFeedResponse,
    DiscoveryPostEntry,
)
from app.services.blocks import filter_blocked_posts, get_blocked_user_ids
from app.services.post_views import annotate_posts_for_user, post_query_options, post_to_read_schema, visible_post_filter

TRENDING_WINDOW_HOURS = 48
FOR_YOU_WINDOW_HOURS = 72
TRENDING_CANDIDATE_LIMIT = 200
FOR_YOU_CANDIDATE_LIMIT = 120


@dataclass(frozen=True)
class RankedDiscoveryPost:
    post: Post
    score: int
    discovery_reason: str | None


def _active_author_filter():
    return User.is_active == True, User.status == UserStatus.ACTIVE


def _base_discovery_query(cutoff: datetime) -> Select[tuple[Post]]:
    return (
        select(Post)
        .join(User, User.id == Post.user_id)
        .options(*post_query_options())
        .where(Post.created_at >= cutoff)
        .where(Post.parent_id == None)
        .where(Post.is_repost == False)
        .where(visible_post_filter())
        .where(*_active_author_filter())
    )


def compute_trending_score(post: Post, now: datetime, *, window_hours: int) -> int:
    age_seconds = max((now - post.created_at).total_seconds(), 0)
    age_hours = age_seconds / 3600
    engagement_score = (post.likes_count * 2) + (post.replies_count * 3) + (post.reposts_count * 4)
    if engagement_score <= 0:
        return 0
    bounded_age_hours = min(age_hours, window_hours)
    return int(round((engagement_score * 100) / (bounded_age_hours + 2)))


def derive_category_label(post: Post) -> str | None:
    if post.media_url:
        return "With media"
    if post.replies_count >= max(post.likes_count, post.reposts_count) and post.replies_count > 0:
        return "Conversation"
    if post.reposts_count >= post.likes_count and post.reposts_count > 0:
        return "Shared widely"
    if post.likes_count > 0:
        return "Popular"
    return None


def _content_preview(post: Post) -> str:
    content = (post.content or "").strip()
    if content:
        return content[:220]
    if post.media_url:
        return "Media post"
    return "Post"


def _sort_ranked_posts(items: list[RankedDiscoveryPost]) -> list[RankedDiscoveryPost]:
    return sorted(
        items,
        key=lambda item: (-item.score, -item.post.created_at.timestamp(), -item.post.id),
    )


def _merge_for_you_rankings(
    primary: Sequence[RankedDiscoveryPost],
    fallback: Sequence[RankedDiscoveryPost],
    *,
    limit: int,
) -> list[RankedDiscoveryPost]:
    if limit <= 0:
        return []
    return list(primary[:limit]) + list(fallback[: max(limit - len(primary), 0)])


def _serialize_entries(
    ranked_posts: Sequence[RankedDiscoveryPost],
    *,
    current_user_id: int | None,
    blocked_user_ids: set[int] | None = None,
) -> list[DiscoveryPostEntry]:
    blocked_user_ids = blocked_user_ids or set()
    entries: list[DiscoveryPostEntry] = []
    for index, ranked in enumerate(ranked_posts, start=1):
        post = ranked.post
        entries.append(
            DiscoveryPostEntry(
                rank=index,
                score=ranked.score,
                post_id=post.id,
                created_at=post.created_at,
                author=DiscoveryAuthorSummary(
                    id=post.author.id,
                    username=post.author.username,
                    display_name=post.author.display_name,
                    avatar_url=post.author.avatar_url,
                ),
                content_preview=_content_preview(post),
                has_media=bool(post.media_url),
                media_url=post.media_url,
                engagement=DiscoveryEngagement(
                    likes=post.likes_count,
                    replies=post.replies_count,
                    reposts=post.reposts_count,
                ),
                category_label=derive_category_label(post),
                discovery_reason=ranked.discovery_reason,
                post=post_to_read_schema(post, current_user_id, blocked_user_ids=blocked_user_ids),
            )
        )
    return entries


async def build_trending_feed(
    db: AsyncSession,
    *,
    current_user_id: int | None,
    limit: int,
    window_hours: int = TRENDING_WINDOW_HOURS,
) -> DiscoveryFeedResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    result = await db.execute(
        _base_discovery_query(cutoff)
        .where((Post.likes_count + Post.replies_count + Post.reposts_count) > 0)
        .order_by(
            Post.likes_count.desc(),
            Post.reposts_count.desc(),
            Post.replies_count.desc(),
            Post.created_at.desc(),
            Post.id.desc(),
        )
        .limit(TRENDING_CANDIDATE_LIMIT)
    )
    posts = result.scalars().all()
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    posts = filter_blocked_posts(posts, blocked_user_ids)
    await annotate_posts_for_user(db, posts, current_user_id)

    ranked = _sort_ranked_posts(_rank_trending_posts(posts, now=now, window_hours=window_hours))[:limit]

    return DiscoveryFeedResponse(
        mode="trending",
        window_hours=window_hours,
        items=_serialize_entries(ranked, current_user_id=current_user_id, blocked_user_ids=blocked_user_ids),
    )


async def build_for_you_feed(
    db: AsyncSession,
    *,
    current_user_id: int | None,
    limit: int,
) -> DiscoveryFeedResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FOR_YOU_WINDOW_HOURS)
    followed_ranked: list[RankedDiscoveryPost] = []
    fallback_ranked: list[RankedDiscoveryPost] = []
    used_post_ids: set[int] = set()

    following_ids: list[int] = []
    if current_user_id is not None:
        follow_result = await db.execute(
            select(Follow.following_id).where(Follow.follower_id == current_user_id)
        )
        following_ids = follow_result.scalars().all()
        blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
        following_ids = [user_id for user_id in following_ids if user_id not in blocked_user_ids]
    else:
        blocked_user_ids = await get_blocked_user_ids(db, current_user_id)

    if following_ids:
            followed_result = await db.execute(
                _base_discovery_query(cutoff)
                .where(Post.user_id.in_(following_ids))
                .order_by(
                    Post.created_at.desc(),
                    Post.likes_count.desc(),
                    Post.reposts_count.desc(),
                    Post.replies_count.desc(),
                    Post.id.desc(),
                )
                .limit(FOR_YOU_CANDIDATE_LIMIT)
            )
            followed_posts = followed_result.scalars().all()
            followed_posts = filter_blocked_posts(followed_posts, blocked_user_ids)
            await annotate_posts_for_user(db, followed_posts, current_user_id)
            followed_ranked.extend(
                RankedDiscoveryPost(
                    post=post,
                    score=compute_trending_score(post, now, window_hours=FOR_YOU_WINDOW_HOURS) + 25,
                    discovery_reason="From people you follow",
                )
                for post in followed_posts
            )
            used_post_ids.update(post.id for post in followed_posts)

    followed_ranked = _sort_ranked_posts(followed_ranked)
    if len(followed_ranked) < limit:
        trending_result = await db.execute(
            _base_discovery_query(now - timedelta(hours=TRENDING_WINDOW_HOURS))
            .where((Post.likes_count + Post.replies_count + Post.reposts_count) > 0)
            .order_by(
                Post.likes_count.desc(),
                Post.reposts_count.desc(),
                Post.replies_count.desc(),
                Post.created_at.desc(),
                Post.id.desc(),
            )
            .limit(TRENDING_CANDIDATE_LIMIT)
        )
        trending_posts = trending_result.scalars().all()
        trending_posts = filter_blocked_posts(trending_posts, blocked_user_ids)
        await annotate_posts_for_user(db, trending_posts, current_user_id)
        for trending in _sort_ranked_posts(_rank_trending_posts(trending_posts, now=now, window_hours=TRENDING_WINDOW_HOURS)):
            if trending.post.id in used_post_ids:
                continue
            fallback_ranked.append(
                RankedDiscoveryPost(
                    post=trending.post,
                    score=trending.score,
                    discovery_reason="Trending beyond your circle",
                )
            )
            used_post_ids.add(trending.post.id)
            if len(followed_ranked) + len(fallback_ranked) >= limit:
                break

    ranked = _merge_for_you_rankings(followed_ranked, fallback_ranked, limit=limit)
    return DiscoveryFeedResponse(
        mode="for_you",
        window_hours=FOR_YOU_WINDOW_HOURS,
        items=_serialize_entries(ranked, current_user_id=current_user_id, blocked_user_ids=blocked_user_ids),
    )


def _rank_trending_posts(posts: Sequence[Post], *, now: datetime, window_hours: int) -> list[RankedDiscoveryPost]:
    return [
        RankedDiscoveryPost(post=post, score=score, discovery_reason=None)
        for post in posts
        if (score := compute_trending_score(post, now, window_hours=window_hours)) > 0
    ]


async def build_discovery_feed(
    db: AsyncSession,
    *,
    mode: Literal["for_you", "trending"],
    current_user_id: int | None,
    limit: int,
) -> DiscoveryFeedResponse:
    if mode == "trending":
        return await build_trending_feed(db, current_user_id=current_user_id, limit=limit, window_hours=TRENDING_WINDOW_HOURS)
    return await build_for_you_feed(db, current_user_id=current_user_id, limit=limit)
