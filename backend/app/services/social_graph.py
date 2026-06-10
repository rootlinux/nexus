from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.follow import Follow
from app.models.invite import InviteCode
from app.models.post import Post, PostModerationStatus
from app.models.user import User, UserStatus
from app.schemas.follow import InviterProfile, SuggestedUser, UserProfile


async def get_follow_counts_map(
    db: AsyncSession,
    user_ids: Iterable[int],
) -> dict[int, dict[str, int]]:
    user_ids = {user_id for user_id in user_ids if user_id is not None}
    if not user_ids:
        return {}

    followers_result = await db.execute(
        select(Follow.following_id, func.count(Follow.id))
        .where(Follow.following_id.in_(user_ids))
        .group_by(Follow.following_id)
    )
    following_result = await db.execute(
        select(Follow.follower_id, func.count(Follow.id))
        .where(Follow.follower_id.in_(user_ids))
        .group_by(Follow.follower_id)
    )

    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"followers_count": 0, "following_count": 0})

    for following_id, count in followers_result.all():
        counts[int(following_id)]["followers_count"] = int(count or 0)

    for follower_id, count in following_result.all():
        counts[int(follower_id)]["following_count"] = int(count or 0)

    return dict(counts)


async def get_content_counts_map(
    db: AsyncSession,
    user_ids: Iterable[int],
) -> dict[int, dict[str, int]]:
    user_ids = {user_id for user_id in user_ids if user_id is not None}
    if not user_ids:
        return {}

    posts_result = await db.execute(
        select(
            Post.user_id,
            func.sum(
                case(
                    (
                        (Post.parent_id.is_(None))
                        & (Post.is_repost == False)
                        & (Post.repost_of_id.is_(None))
                        & (Post.moderation_status == PostModerationStatus.VISIBLE),
                        1,
                    ),
                    else_=0,
                )
            ).label("posts_count"),
            func.sum(
                case(
                    (
                        (Post.parent_id.is_not(None))
                        & (Post.is_repost == False)
                        & (Post.repost_of_id.is_(None))
                        & (Post.moderation_status == PostModerationStatus.VISIBLE)
                        & Post.parent.has(Post.moderation_status == PostModerationStatus.VISIBLE),
                        1,
                    ),
                    else_=0,
                )
            ).label("replies_count"),
            func.sum(
                case(
                    (
                        (Post.is_repost == True)
                        & (Post.repost_of_id.is_not(None))
                        & (Post.moderation_status == PostModerationStatus.VISIBLE),
                        1,
                    ),
                    else_=0,
                )
            ).label("reposts_count"),
        )
        .where(Post.user_id.in_(user_ids))
        .group_by(Post.user_id)
    )

    counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {"posts_count": 0, "replies_count": 0, "reposts_count": 0}
    )
    for row in posts_result.all():
        counts[int(row.user_id)] = {
            "posts_count": int(row.posts_count or 0),
            "replies_count": int(row.replies_count or 0),
            "reposts_count": int(row.reposts_count or 0),
        }

    return dict(counts)


async def get_following_ids_for_user(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(select(Follow.following_id).where(Follow.follower_id == user_id))
    return {following_id for following_id in result.scalars().all() if following_id is not None}


async def get_follower_ids_for_user(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(select(Follow.follower_id).where(Follow.following_id == user_id))
    return {follower_id for follower_id in result.scalars().all() if follower_id is not None}


async def get_following_state_map(
    db: AsyncSession,
    current_user_id: Optional[int],
    candidate_ids: Iterable[int],
) -> dict[int, bool]:
    candidate_ids = {candidate_id for candidate_id in candidate_ids if candidate_id is not None}
    if not current_user_id or not candidate_ids:
        return {candidate_id: False for candidate_id in candidate_ids}

    result = await db.execute(
        select(Follow.following_id)
        .where(
            Follow.follower_id == current_user_id,
            Follow.following_id.in_(candidate_ids),
        )
    )
    followed_ids = {following_id for following_id in result.scalars().all() if following_id is not None}
    return {candidate_id: candidate_id in followed_ids for candidate_id in candidate_ids}


async def get_assigned_invite_for_user(db: AsyncSession, user: User, current_user_id: Optional[int]) -> dict | None:
    if current_user_id != user.id:
        return None

    invite_result = await db.execute(
        select(InviteCode)
        .options(selectinload(InviteCode.used_by_user))
        .where(
            (InviteCode.assigned_to_user_id == user.id)
            | (InviteCode.assigned_to_username == user.username)
        )
        .order_by(InviteCode.created_at.desc())
        .limit(1)
    )
    invite = invite_result.scalars().first()
    if not invite:
        return None

    now = datetime.now(timezone.utc)
    if invite.current_uses >= 1 or invite.used_by_user_id or invite.used_at:
        invite_status = "used"
    elif invite.expires_at and invite.expires_at < now:
        invite_status = "expired"
    elif not invite.is_active:
        invite_status = "inactive"
    else:
        invite_status = "active"

    return {
        "id": invite.id,
        "code": invite.code,
        "internal_note": invite.internal_note,
        "status": invite_status,
        "expires_at": invite.expires_at,
        "used_at": invite.used_at,
        "invited_user_id": invite.used_by_user_id,
        "invited_username": invite.used_by_user.username if getattr(invite, "used_by_user", None) else None,
    }


def build_user_profile(
    user: User,
    *,
    is_following: bool,
    is_blocked_by_me: bool = False,
    has_blocked_me: bool = False,
    is_access_limited: bool = False,
    follow_counts: dict[str, int] | None = None,
    content_counts: dict[str, int] | None = None,
    assigned_invite: dict | None = None,
) -> UserProfile:
    follow_counts = follow_counts or {}
    content_counts = content_counts or {}

    return UserProfile(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        cover_url=user.cover_url,
        bio=user.bio,
        location=user.location,
        website=user.website,
        created_at=user.created_at,
        is_following=is_following,
        followers_count=int(follow_counts.get("followers_count", 0)),
        following_count=int(follow_counts.get("following_count", 0)),
        posts_count=int(content_counts.get("posts_count", 0)),
        replies_count=int(content_counts.get("replies_count", 0)),
        reposts_count=int(content_counts.get("reposts_count", 0)),
        is_blocked_by_me=is_blocked_by_me,
        has_blocked_me=has_blocked_me,
        is_access_limited=is_access_limited,
        assigned_invite=assigned_invite,
        inviter=(
            InviterProfile(
                id=user.inviter.id,
                username=user.inviter.username,
                display_name=user.inviter.display_name,
                avatar_url=user.inviter.avatar_url,
            )
            if getattr(user, "inviter", None)
            else None
        ),
    )


async def build_suggested_users(
    db: AsyncSession,
    current_user: User,
    limit: int,
) -> Sequence[SuggestedUser]:
    my_following_ids = await get_following_ids_for_user(db, current_user.id)
    my_follower_ids = await get_follower_ids_for_user(db, current_user.id)
    excluded_ids = set(my_following_ids)
    excluded_ids.add(current_user.id)

    second_degree_counts: dict[int, int] = {}
    if my_following_ids:
        second_degree_result = await db.execute(
            select(Follow.following_id, func.count(Follow.id))
            .where(
                Follow.follower_id.in_(my_following_ids),
                Follow.following_id.not_in(excluded_ids),
            )
            .group_by(Follow.following_id)
        )
        second_degree_counts = {
            int(user_id): int(count or 0)
            for user_id, count in second_degree_result.all()
            if user_id is not None
        }

    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    activity_result = await db.execute(
        select(Post.user_id, func.count(Post.id))
        .where(
            Post.created_at >= recent_cutoff,
            Post.user_id.not_in(excluded_ids),
            Post.parent_id.is_(None),
        )
        .group_by(Post.user_id)
    )
    recent_activity_counts = {
        int(user_id): int(count or 0)
        for user_id, count in activity_result.all()
        if user_id is not None
    }

    candidate_ids = set(second_degree_counts) | set(my_follower_ids) | set(recent_activity_counts)
    candidate_ids -= excluded_ids
    if not candidate_ids:
        return []

    users_result = await db.execute(
        select(User)
        .options(selectinload(User.inviter))
        .where(User.id.in_(candidate_ids))
        .where(User.is_active == True, User.status == UserStatus.ACTIVE)
        .order_by(User.created_at.desc())
    )
    users = users_result.scalars().all()
    if not users:
        return []

    follow_counts_map = await get_follow_counts_map(db, candidate_ids)
    content_counts_map = await get_content_counts_map(db, candidate_ids)

    suggestions: list[SuggestedUser] = []
    for user in users:
        second_degree = second_degree_counts.get(user.id, 0)
        follows_you = 1 if user.id in my_follower_ids else 0
        recent_posts = min(recent_activity_counts.get(user.id, 0), 5)
        total_followers = min(follow_counts_map.get(user.id, {}).get("followers_count", 0), 20)

        score = (second_degree * 5) + (follows_you * 4) + (recent_posts * 2) + total_followers
        if score <= 0:
            continue

        reason_parts: list[str] = []
        if second_degree:
            label = "people you follow also follow them"
            if second_degree > 1:
                label = f"{second_degree} people you follow also follow them"
            reason_parts.append(label)
        if follows_you:
            reason_parts.append("they follow you")
        if recent_posts:
            reason_parts.append("recently active")

        base_profile = build_user_profile(
            user,
            is_following=False,
            follow_counts=follow_counts_map.get(user.id),
            content_counts=content_counts_map.get(user.id),
        )
        suggestions.append(
            SuggestedUser(
                **base_profile.model_dump(),
                score=score,
                reason=", ".join(reason_parts) or "active account",
            )
        )

    suggestions.sort(key=lambda item: (-item.score, item.username.lower()))
    return suggestions[:limit]
