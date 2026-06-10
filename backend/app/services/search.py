from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.post import Post
from app.models.user import User, UserStatus
from app.schemas.search import SearchResponse, SearchType
from app.services.blocks import filter_blocked_posts, filter_blocked_users, get_blocked_user_ids
from app.services.discovery import TRENDING_WINDOW_HOURS, compute_trending_score
from app.services.post_views import annotate_posts_for_user, post_query_options, post_to_read_schema, visible_post_filter
from app.services.social_graph import build_user_profile, get_content_counts_map, get_follow_counts_map, get_following_state_map

PEOPLE_LIMIT = 20
TOP_PEOPLE_LIMIT = 8
POST_LIMIT = 20
TOP_POST_LIMIT = 12
TOP_POST_CANDIDATE_LIMIT = 100


@dataclass(frozen=True)
class RankedSearchPost:
    post: Post
    match_rank: int
    score: int


def _normalize_query(query: str) -> str:
    return query.strip()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _empty_response(query: str, search_type: SearchType) -> SearchResponse:
    return SearchResponse(query=query, type=search_type, posts=[], users=[])


def _active_user_filter():
    return User.is_active == True, User.status == UserStatus.ACTIVE


def _people_match_order(query: str):
    lowered_query = query.lower()
    escaped_query = _escape_like(lowered_query)
    username_lower = func.lower(User.username)
    display_name_lower = func.lower(func.coalesce(User.display_name, ""))

    return case(
        (username_lower == lowered_query, 0),
        (display_name_lower == lowered_query, 1),
        (username_lower.like(f"{escaped_query}%", escape="\\"), 2),
        (display_name_lower.like(f"{escaped_query}%", escape="\\"), 3),
        else_=4,
    )


async def _serialize_user_profiles(
    db: AsyncSession,
    users: list[User],
    *,
    current_user_id: int | None,
) -> list:
    if not users:
        return []

    user_ids = [user.id for user in users]
    follow_counts_map = await get_follow_counts_map(db, user_ids)
    content_counts_map = await get_content_counts_map(db, user_ids)
    following_state_map = await get_following_state_map(db, current_user_id, user_ids)

    return [
        build_user_profile(
            user,
            is_following=following_state_map.get(user.id, False),
            follow_counts=follow_counts_map.get(user.id),
            content_counts=content_counts_map.get(user.id),
        )
        for user in users
    ]


async def search_people(
    db: AsyncSession,
    *,
    query: str,
    current_user_id: int | None,
    limit: int = PEOPLE_LIMIT,
):
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return []

    lowered_query = normalized_query.lower()
    escaped_query = _escape_like(lowered_query)
    username_lower = func.lower(User.username)
    display_name_lower = func.lower(func.coalesce(User.display_name, ""))
    contains_pattern = f"%{escaped_query}%"

    result = await db.execute(
        select(User)
        .options(selectinload(User.inviter))
        .where(*_active_user_filter())
        .where(
            or_(
                username_lower.like(contains_pattern, escape="\\"),
                display_name_lower.like(contains_pattern, escape="\\"),
            )
        )
        .order_by(
            _people_match_order(normalized_query),
            func.lower(User.username),
            User.id.asc(),
        )
        .limit(limit)
    )
    users = list(result.scalars().all())
    users = filter_blocked_users(users, await get_blocked_user_ids(db, current_user_id))
    return await _serialize_user_profiles(db, users, current_user_id=current_user_id)


def _base_post_search_query():
    return (
        select(Post)
        .join(User, User.id == Post.user_id)
        .options(*post_query_options())
        .where(visible_post_filter())
        .where(*_active_user_filter())
        .where(Post.is_repost == False)
    )


def _post_match_rank(post: Post, query: str) -> int:
    content = (post.content or "").strip().lower()
    lowered_query = query.lower()

    if content == lowered_query:
        return 3
    if content.startswith(lowered_query):
        return 2
    if lowered_query in content:
        return 1
    return 0


def _rank_top_posts(posts: list[Post], *, query: str, now: datetime) -> list[RankedSearchPost]:
    ranked: list[RankedSearchPost] = []
    for post in posts:
        match_rank = _post_match_rank(post, query)
        if match_rank <= 0:
            continue
        discovery_score = compute_trending_score(post, now, window_hours=TRENDING_WINDOW_HOURS)
        score = (match_rank * 10_000) + discovery_score
        ranked.append(RankedSearchPost(post=post, match_rank=match_rank, score=score))

    return sorted(
        ranked,
        key=lambda item: (
            -item.match_rank,
            -item.score,
            -item.post.created_at.timestamp(),
            -item.post.id,
        ),
    )


async def search_latest_posts(
    db: AsyncSession,
    *,
    query: str,
    current_user_id: int | None,
    limit: int = POST_LIMIT,
):
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return []

    escaped_query = _escape_like(normalized_query)
    contains_pattern = f"%{escaped_query}%"
    result = await db.execute(
        _base_post_search_query()
        .where(Post.content.ilike(contains_pattern, escape="\\"))
        .order_by(Post.created_at.desc(), Post.id.desc())
        .limit(limit)
    )
    posts = list(result.scalars().all())
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    posts = filter_blocked_posts(posts, blocked_user_ids)
    await annotate_posts_for_user(db, posts, current_user_id)
    return [post_to_read_schema(post, current_user_id, blocked_user_ids=blocked_user_ids) for post in posts]


async def search_top_posts(
    db: AsyncSession,
    *,
    query: str,
    current_user_id: int | None,
    limit: int = TOP_POST_LIMIT,
):
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return []

    escaped_query = _escape_like(normalized_query)
    contains_pattern = f"%{escaped_query}%"
    candidate_result = await db.execute(
        _base_post_search_query()
        .where(Post.content.ilike(contains_pattern, escape="\\"))
        .order_by(
            Post.likes_count.desc(),
            Post.reposts_count.desc(),
            Post.replies_count.desc(),
            Post.created_at.desc(),
            Post.id.desc(),
        )
        .limit(TOP_POST_CANDIDATE_LIMIT)
    )
    candidates = list(candidate_result.scalars().all())
    blocked_user_ids = await get_blocked_user_ids(db, current_user_id)
    candidates = filter_blocked_posts(candidates, blocked_user_ids)
    await annotate_posts_for_user(db, candidates, current_user_id)

    ranked = _rank_top_posts(candidates, query=normalized_query, now=datetime.now(timezone.utc))[:limit]
    return [post_to_read_schema(item.post, current_user_id, blocked_user_ids=blocked_user_ids) for item in ranked]


async def perform_search(
    db: AsyncSession,
    *,
    query: str,
    search_type: SearchType,
    current_user_id: int | None,
) -> SearchResponse:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return _empty_response(normalized_query, search_type)

    if search_type == "people":
        users = await search_people(db, query=normalized_query, current_user_id=current_user_id, limit=PEOPLE_LIMIT)
        return SearchResponse(query=normalized_query, type=search_type, posts=[], users=users)

    if search_type == "latest":
        posts = await search_latest_posts(db, query=normalized_query, current_user_id=current_user_id, limit=POST_LIMIT)
        return SearchResponse(query=normalized_query, type=search_type, posts=posts, users=[])

    users = await search_people(db, query=normalized_query, current_user_id=current_user_id, limit=TOP_PEOPLE_LIMIT)
    posts = await search_top_posts(db, query=normalized_query, current_user_id=current_user_id, limit=TOP_POST_LIMIT)
    return SearchResponse(query=normalized_query, type=search_type, posts=posts, users=users)
