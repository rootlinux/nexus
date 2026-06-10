from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.post import Post, PostModerationStatus
from app.models.user import User, UserStatus
from app.schemas.follow import DiscoverUserEntry, DiscoverUsersResponse
from app.schemas.post import (
    DiscoverPostsResponse,
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


# ---------------------------------------------------------------------------
# Discover: Users
# ---------------------------------------------------------------------------

_DISCOVER_USERS_NEW_DAYS = 7
_DISCOVER_USERS_ACTIVITY_DAYS = 7


async def build_discover_users(
    db: AsyncSession,
    *,
    current_user_id: int,
    limit: int,
    offset: int,
) -> DiscoverUsersResponse:
    """Return ranked user suggestions for the Discover page.

    Score formula:
        score = (mutual_count × 3) + (is_new × 2) + (recent_activity × 1)

    Excludes:
    - the requesting user themselves
    - users already followed by the requesting user
    - non-ACTIVE users
    """
    now = datetime.now(timezone.utc)
    # User.created_at is stored as naive UTC in the DB
    new_cutoff = now - timedelta(days=_DISCOVER_USERS_NEW_DAYS)
    new_cutoff_naive = new_cutoff.replace(tzinfo=None)
    activity_cutoff = now - timedelta(days=_DISCOVER_USERS_ACTIVITY_DAYS)

    # IDs that the current user already follows
    already_following_sq = (
        select(Follow.following_id)
        .where(Follow.follower_id == current_user_id)
        .scalar_subquery()
    )

    # mutual_count: number of people among those the current_user follows
    # who also follow the candidate user
    mutual_count_sq = (
        select(func.count())
        .select_from(Follow)
        .where(
            Follow.follower_id.in_(
                select(Follow.following_id).where(Follow.follower_id == current_user_id)
            ),
            Follow.following_id == User.id,
        )
        .correlate(User)
        .scalar_subquery()
    )

    # Fetch candidate pool — score & sort in Python to keep query simple
    candidate_result = await db.execute(
        select(
            User.id,
            User.username,
            User.display_name,
            User.avatar_url,
            User.created_at,
            mutual_count_sq.label("mutual_count"),
        )
        .where(User.id != current_user_id)
        .where(User.status == UserStatus.ACTIVE)
        .where(User.is_active == True)
        .where(User.id.not_in(already_following_sq))
        .order_by(mutual_count_sq.desc(), User.created_at.desc())
        .limit(max(limit * 5, 200))
    )
    candidates = candidate_result.all()

    if not candidates:
        return DiscoverUsersResponse(users=[], total=0, limit=limit, offset=offset, has_more=False)

    candidate_ids = [row.id for row in candidates]

    # recent_activity: did this user post any top-level visible post in the last 7 days?
    activity_result = await db.execute(
        select(Post.user_id)
        .where(Post.user_id.in_(candidate_ids))
        .where(Post.created_at >= activity_cutoff)
        .where(Post.moderation_status == PostModerationStatus.VISIBLE)
        .where(Post.parent_id == None)
        .distinct()
    )
    active_user_ids: set[int] = {row.user_id for row in activity_result.all()}

    # Score and rank in Python
    ranked: list[tuple[int, DiscoverUserEntry]] = []
    for row in candidates:
        mutual = int(row.mutual_count or 0)
        # created_at may be naive or aware depending on DB driver — normalise
        created = row.created_at
        if created.tzinfo is None:
            is_new = 1 if created >= new_cutoff_naive else 0
        else:
            is_new = 1 if created >= new_cutoff else 0
        recent = 1 if row.id in active_user_ids else 0
        score = (mutual * 3) + (is_new * 2) + (recent * 1)
        ranked.append((score, DiscoverUserEntry(
            id=row.id,
            username=row.username,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
            mutual_count=mutual,
            score=score,
        )))

    ranked.sort(key=lambda t: (-t[0], t[1].id))
    total = len(ranked)
    page = [entry for _, entry in ranked[offset: offset + limit]]

    return DiscoverUsersResponse(
        users=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


# ---------------------------------------------------------------------------
# Discover: Posts
# ---------------------------------------------------------------------------

_DISCOVER_POSTS_WINDOW_DAYS = 7


async def build_discover_posts(
    db: AsyncSession,
    *,
    current_user_id: int,
    limit: int,
    offset: int,
) -> DiscoverPostsResponse:
    """Return trending posts for the Discover page.

    - Last 7 days, VISIBLE, top-level only (parent_id IS NULL)
    - Sorted by (likes_count + replies_count) DESC
    - Paginated
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_DISCOVER_POSTS_WINDOW_DAYS)

    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)

    base_q = (
        select(Post)
        .join(User, User.id == Post.user_id)
        .options(*post_query_options())
        .where(Post.created_at >= cutoff)
        .where(Post.parent_id == None)
        .where(Post.moderation_status == PostModerationStatus.VISIBLE)
        .where(User.status == UserStatus.ACTIVE)
        .where(User.is_active == True)
    )

    if blocked_user_ids:
        base_q = base_q.where(Post.user_id.not_in(blocked_user_ids))

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_q
        .order_by(
            (Post.likes_count + Post.replies_count).desc(),
            Post.created_at.desc(),
            Post.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    posts = result.scalars().all()

    await annotate_posts_for_user(db, posts, current_user_id)

    post_reads = [
        post_to_read_schema(post, current_user_id, blocked_user_ids=blocked_user_ids)
        for post in posts
    ]

    return DiscoverPostsResponse(
        posts=post_reads,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )
