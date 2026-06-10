from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.follow import Follow


@dataclass(frozen=True)
class BlockRelationship:
    blocked_by_me: bool = False
    has_blocked_me: bool = False

    @property
    def is_blocked(self) -> bool:
        return self.blocked_by_me or self.has_blocked_me


async def get_block_relationship(
    db: AsyncSession,
    *,
    current_user_id: int | None,
    target_user_id: int,
) -> BlockRelationship:
    if not current_user_id or current_user_id == target_user_id:
        return BlockRelationship()

    result = await db.execute(
        select(Block.blocker_id, Block.blocked_id).where(
            or_(
                and_(Block.blocker_id == current_user_id, Block.blocked_id == target_user_id),
                and_(Block.blocker_id == target_user_id, Block.blocked_id == current_user_id),
            )
        )
    )

    blocked_by_me = False
    has_blocked_me = False
    for blocker_id, blocked_id in result.all():
        if blocker_id == current_user_id and blocked_id == target_user_id:
            blocked_by_me = True
        elif blocker_id == target_user_id and blocked_id == current_user_id:
            has_blocked_me = True

    return BlockRelationship(blocked_by_me=blocked_by_me, has_blocked_me=has_blocked_me)


async def get_blocked_user_ids(db: AsyncSession, current_user_id: int | None) -> set[int]:
    if not current_user_id:
        return set()

    result = await db.execute(
        select(Block.blocker_id, Block.blocked_id).where(
            or_(Block.blocker_id == current_user_id, Block.blocked_id == current_user_id)
        )
    )

    blocked_user_ids: set[int] = set()
    for blocker_id, blocked_id in result.all():
        if blocker_id == current_user_id:
            blocked_user_ids.add(blocked_id)
        else:
            blocked_user_ids.add(blocker_id)
    return blocked_user_ids


def filter_blocked_users(items, blocked_user_ids: set[int]):
    if not blocked_user_ids:
        return list(items)
    return [item for item in items if getattr(item, "id", None) not in blocked_user_ids]


def filter_blocked_posts(items, blocked_user_ids: set[int]):
    if not blocked_user_ids:
        return list(items)
    return [item for item in items if getattr(item, "user_id", None) not in blocked_user_ids]


def raise_blocked_profile_error() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def raise_blocked_interaction_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This action isn't available because one of you has blocked the other.",
    )


def raise_blocked_conversation_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Conversation not found",
    )


async def enforce_no_block_relationship(
    db: AsyncSession,
    *,
    current_user_id: int | None,
    target_user_id: int,
    not_found_for_profile: bool = False,
) -> BlockRelationship:
    relationship = await get_block_relationship(
        db,
        current_user_id=current_user_id,
        target_user_id=target_user_id,
    )
    if not relationship.is_blocked:
        return relationship

    if not_found_for_profile:
        raise_blocked_profile_error()
    raise_blocked_interaction_error()


async def remove_follow_relationships_between(db: AsyncSession, user_a_id: int, user_b_id: int) -> None:
    await db.execute(
        delete(Follow).where(
            or_(
                and_(Follow.follower_id == user_a_id, Follow.following_id == user_b_id),
                and_(Follow.follower_id == user_b_id, Follow.following_id == user_a_id),
            )
        )
    )
