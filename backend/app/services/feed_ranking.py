from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import log1p
from typing import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetime_utils import ensure_utc_datetime
from app.models.follow import Follow
from app.models.moderation_signal import (
    ModerationDetectionStatus,
    ModerationReviewStatus,
    ModerationSignal,
)
from app.models.post import Post
from app.models.user import User, UserStatus
from app.schemas.post import FeedResponse
from app.services.blocks import filter_blocked_posts, get_blocked_user_ids
from app.services.post_views import annotate_posts_for_user, post_query_options, post_to_read_schema, visible_post_filter

HOME_FEED_BASE_CANDIDATE_LIMIT = 400
HOME_FEED_MAX_CANDIDATE_LIMIT = 1000


@dataclass(frozen=True)
class ModerationSignalSummary:
    open_suspicious_count: int = 0
    resolved_suspicious_count: int = 0
    open_blocked_count: int = 0
    resolved_blocked_count: int = 0


@dataclass(frozen=True)
class FeedRankingContext:
    current_user_id: int
    current_user_invited_by_user_id: int | None
    following_ids: frozenset[int]
    second_degree_ids: frozenset[int]
    author_signal_map: dict[int, ModerationSignalSummary]
    post_signal_map: dict[int, ModerationSignalSummary]


@dataclass(frozen=True)
class FeedScoreBreakdown:
    follow_boost: int
    network_proximity_boost: int
    reputation_boost: int
    engagement_score: int
    freshness_score: int
    moderation_penalty: int

    @property
    def total(self) -> int:
        return (
            self.follow_boost
            + self.network_proximity_boost
            + self.reputation_boost
            + self.engagement_score
            + self.freshness_score
            - self.moderation_penalty
        )


@dataclass(frozen=True)
class RankedFeedPost:
    post: Post
    score: int
    feed_reason: str | None
    breakdown: FeedScoreBreakdown


def _active_author_filter():
    return User.is_active == True, User.status == UserStatus.ACTIVE


def _base_home_feed_query() -> Select[tuple[Post]]:
    return (
        select(Post)
        .join(User, User.id == Post.user_id)
        .options(*post_query_options())
        .where(Post.parent_id == None)
        .where(Post.is_repost == False)
        .where(visible_post_filter())
        .where(*_active_author_filter())
    )


def _engagement_score(post: Post) -> int:
    likes_component = int(round(log1p(max(post.likes_count, 0)) * 12))
    replies_component = int(round(log1p(max(post.replies_count, 0)) * 18))
    reposts_component = int(round(log1p(max(post.reposts_count, 0)) * 16))
    return likes_component + replies_component + reposts_component


def _post_created_at_utc(post: Post) -> datetime:
    created_at = ensure_utc_datetime(post.created_at)
    if created_at is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return created_at


def _utc_datetime(value: datetime) -> datetime:
    normalized = ensure_utc_datetime(value)
    if normalized is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return normalized


def _freshness_score(post: Post, now: datetime) -> int:
    age_hours = max((_utc_datetime(now) - _post_created_at_utc(post)).total_seconds() / 3600, 0)
    return int(round(140 / (1 + (age_hours / 8))))


def _reputation_boost(post: Post, context: FeedRankingContext) -> int:
    boost = 0
    author = post.author
    if author.invited_by_user_id is not None:
        boost += 10
    if author.invited_by_user_id and author.invited_by_user_id in context.following_ids:
        boost += 22
    if context.current_user_invited_by_user_id and author.invited_by_user_id == context.current_user_invited_by_user_id:
        boost += 12
    return boost


def _moderation_penalty(post: Post, context: FeedRankingContext) -> int:
    author_signals = context.author_signal_map.get(post.user_id, ModerationSignalSummary())
    post_signals = context.post_signal_map.get(post.id, ModerationSignalSummary())

    return (
        (author_signals.open_suspicious_count * 32)
        + (author_signals.resolved_suspicious_count * 10)
        + (author_signals.open_blocked_count * 60)
        + (author_signals.resolved_blocked_count * 18)
        + (post_signals.open_suspicious_count * 44)
        + (post_signals.resolved_suspicious_count * 14)
        + (post_signals.open_blocked_count * 80)
        + (post_signals.resolved_blocked_count * 24)
    )


def _score_breakdown(post: Post, context: FeedRankingContext, *, now: datetime) -> FeedScoreBreakdown:
    author_id = post.user_id
    follow_boost = 160 if author_id == context.current_user_id or author_id in context.following_ids else 0
    network_proximity_boost = 55 if author_id in context.second_degree_ids else 0
    reputation_boost = _reputation_boost(post, context)
    engagement_score = _engagement_score(post)
    freshness_score = _freshness_score(post, now)
    moderation_penalty = _moderation_penalty(post, context)

    return FeedScoreBreakdown(
        follow_boost=follow_boost,
        network_proximity_boost=network_proximity_boost,
        reputation_boost=reputation_boost,
        engagement_score=engagement_score,
        freshness_score=freshness_score,
        moderation_penalty=moderation_penalty,
    )


def _derive_feed_reason(post: Post, context: FeedRankingContext, breakdown: FeedScoreBreakdown) -> str | None:
    author_id = post.user_id
    if author_id == context.current_user_id or author_id in context.following_ids:
        return "From people you follow"
    if (
        author_id in context.second_degree_ids
        or (post.author.invited_by_user_id and post.author.invited_by_user_id in context.following_ids)
        or (
            context.current_user_invited_by_user_id
            and post.author.invited_by_user_id == context.current_user_invited_by_user_id
        )
    ):
        return "Popular in your network"
    if breakdown.engagement_score >= 24:
        return "Trending beyond your network"
    return None


def rank_home_feed_candidates(
    posts: Sequence[Post],
    context: FeedRankingContext,
    *,
    now: datetime,
) -> list[RankedFeedPost]:
    ranked: list[RankedFeedPost] = []
    for post in posts:
        breakdown = _score_breakdown(post, context, now=now)
        ranked.append(
            RankedFeedPost(
                post=post,
                score=breakdown.total,
                feed_reason=_derive_feed_reason(post, context, breakdown),
                breakdown=breakdown,
            )
        )

    return sorted(
        ranked,
        key=lambda item: (
            -item.score,
            -_post_created_at_utc(item.post).timestamp(),
            -item.post.id,
        ),
    )


async def _load_following_ids(db: AsyncSession, current_user_id: int) -> set[int]:
    result = await db.execute(
        select(Follow.following_id).where(Follow.follower_id == current_user_id)
    )
    return set(result.scalars().all())


async def _load_second_degree_ids(
    db: AsyncSession,
    *,
    current_user_id: int,
    following_ids: set[int],
) -> set[int]:
    if not following_ids:
        return set()

    result = await db.execute(
        select(Follow.following_id)
        .where(Follow.follower_id.in_(following_ids))
        .where(Follow.following_id != current_user_id)
    )
    return {
        user_id
        for user_id in result.scalars().all()
        if user_id not in following_ids
    }


async def _load_signal_map(
    db: AsyncSession,
    *,
    group_field,
    target_ids: set[int],
) -> dict[int, ModerationSignalSummary]:
    if not target_ids:
        return {}

    result = await db.execute(
        select(
            group_field,
            ModerationSignal.detection_status,
            ModerationSignal.review_status,
            func.count(ModerationSignal.id),
        )
        .where(group_field.in_(target_ids))
        .group_by(group_field, ModerationSignal.detection_status, ModerationSignal.review_status)
    )

    signal_map: dict[int, ModerationSignalSummary] = {}
    for target_id, detection_status, review_status, count in result.all():
        current = signal_map.get(target_id, ModerationSignalSummary())
        updates = {
            "open_suspicious_count": current.open_suspicious_count,
            "resolved_suspicious_count": current.resolved_suspicious_count,
            "open_blocked_count": current.open_blocked_count,
            "resolved_blocked_count": current.resolved_blocked_count,
        }
        if detection_status == ModerationDetectionStatus.SUSPICIOUS:
            if review_status == ModerationReviewStatus.OPEN:
                updates["open_suspicious_count"] += count
            else:
                updates["resolved_suspicious_count"] += count
        elif detection_status == ModerationDetectionStatus.BLOCKED:
            if review_status == ModerationReviewStatus.OPEN:
                updates["open_blocked_count"] += count
            else:
                updates["resolved_blocked_count"] += count

        signal_map[target_id] = ModerationSignalSummary(**updates)

    return signal_map


async def build_feed_ranking_context(
    db: AsyncSession,
    *,
    current_user: User,
    posts: Sequence[Post],
) -> FeedRankingContext:
    following_ids = await _load_following_ids(db, current_user.id)
    second_degree_ids = await _load_second_degree_ids(
        db,
        current_user_id=current_user.id,
        following_ids=following_ids,
    )
    author_ids = {post.user_id for post in posts}
    post_ids = {post.id for post in posts}

    author_signal_map = await _load_signal_map(
        db,
        group_field=ModerationSignal.user_id,
        target_ids=author_ids,
    )
    post_signal_map = await _load_signal_map(
        db,
        group_field=ModerationSignal.post_id,
        target_ids=post_ids,
    )

    return FeedRankingContext(
        current_user_id=current_user.id,
        current_user_invited_by_user_id=current_user.invited_by_user_id,
        following_ids=frozenset(following_ids),
        second_degree_ids=frozenset(second_degree_ids),
        author_signal_map=author_signal_map,
        post_signal_map=post_signal_map,
    )


async def build_home_feed(
    db: AsyncSession,
    *,
    current_user: User,
    cursor: int | None,
    limit: int,
) -> FeedResponse:
    offset = max(cursor or 0, 0)
    candidate_limit = min(
        max(HOME_FEED_BASE_CANDIDATE_LIMIT, offset + (limit * 8)),
        HOME_FEED_MAX_CANDIDATE_LIMIT,
    )
    candidate_result = await db.execute(
        _base_home_feed_query()
        .order_by(Post.created_at.desc(), Post.id.desc())
        .limit(candidate_limit)
    )
    candidate_posts = list(candidate_result.scalars().all())
    blocked_user_ids = await get_blocked_user_ids(db, current_user.id)
    candidate_posts = filter_blocked_posts(candidate_posts, blocked_user_ids)
    await annotate_posts_for_user(db, candidate_posts, current_user.id)

    context = await build_feed_ranking_context(
        db,
        current_user=current_user,
        posts=candidate_posts,
    )
    ranked_candidates = rank_home_feed_candidates(candidate_posts, context, now=datetime.now(timezone.utc))
    page = ranked_candidates[offset : offset + limit]

    posts = []
    for ranked in page:
        post_schema = post_to_read_schema(ranked.post, current_user.id, blocked_user_ids=blocked_user_ids)
        post_schema.feed_reason = ranked.feed_reason
        posts.append(post_schema)

    next_cursor = offset + limit if offset + limit < len(ranked_candidates) else None
    return FeedResponse(posts=posts, next_cursor=next_cursor, has_more=next_cursor is not None)
