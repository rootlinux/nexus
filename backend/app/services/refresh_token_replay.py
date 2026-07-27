from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.refresh_token_family import RefreshTokenFamily


async def lock_token_family(db: AsyncSession, *, token_family_id: str) -> None:
    """The single serialization point for every operation that touches a
    refresh-token family — ordinary rotation and family-wide replay
    revocation alike. Locks the family's own anchor row, never a
    RefreshToken row, so the lock target is unambiguous regardless of how
    many tokens the family currently has. Whichever transaction acquires
    this first fully commits before the other proceeds and re-reads fresh,
    post-commit state — this is what closes the ancestor-replay-vs-
    descendant-rotation race: two concurrent requests touching two
    different RefreshToken rows in the same family would never otherwise
    contend on either row's own lock."""
    await db.execute(
        select(RefreshTokenFamily.token_family_id)
        .where(RefreshTokenFamily.token_family_id == token_family_id)
        .with_for_update()
    )


async def revoke_token_family(db: AsyncSession, *, token_family_id: str, reason: str) -> int:
    """Acquires lock_token_family BEFORE the bulk UPDATE. Whichever of
    revoke_token_family or a concurrent rotation for this family acquires
    the lock first runs to completion (full commit) before the other
    proceeds; if rotation won first, its newly-created child token is
    already committed and unrevoked by the time this function's bulk
    UPDATE runs, so the UPDATE's own WHERE clause (token_family_id + NOT
    revoked) naturally sweeps that child up too — no valid child remains
    after replay revocation wins, either way."""
    await lock_token_family(db, token_family_id=token_family_id)
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_family_id == token_family_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    return result.rowcount
