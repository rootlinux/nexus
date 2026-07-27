import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media_asset import MediaAsset, MediaAssetStatus, MediaAssetType
from app.models.user_media_quota import UserMediaQuota
from app.storage import get_storage_provider

logger = logging.getLogger(__name__)


async def register_pending_media(
    db: AsyncSession, *, owner_user_id: int, media_type: MediaAssetType,
    storage_key: str, content_type: str, file_size_bytes: int,
) -> MediaAsset:
    """Flush-only — never commits. The operation-level caller (see
    run_media_operation) owns the single transaction this participates in."""
    asset = MediaAsset(
        owner_user_id=owner_user_id, media_type=media_type, storage_key=storage_key,
        content_type=content_type, file_size_bytes=file_size_bytes,
    )
    db.add(asset)
    await db.flush()
    return asset


async def attach_pending_media(
    db: AsyncSession, *, storage_key: str, owner_user_id: int, attached_to_type: str, attached_to_id: int,
) -> None:
    """Used ONLY when creating NEW content — avatar/cover upload completion,
    post creation, feedback submission. No legacy bypass: REQUIRES a
    tracked PENDING row owned by the caller. A missing/foreign/non-pending
    row is rejected with 400 — never silently allowed through. The
    backward-compatibility exception this plan makes elsewhere applies only
    to reading/rendering/deleting EXISTING legacy database records (a post
    or avatar/cover created before this feature existed) — never to
    creating new content, which is what this function guards."""
    asset = await db.scalar(
        select(MediaAsset).where(MediaAsset.storage_key == storage_key).with_for_update()
    )
    if asset is None or asset.owner_user_id != owner_user_id or asset.status != MediaAssetStatus.PENDING:
        raise HTTPException(400, "This media is not available to attach.")
    asset.status = MediaAssetStatus.ATTACHED
    asset.attached_to_type = attached_to_type
    asset.attached_to_id = attached_to_id
    asset.attached_at = datetime.now(timezone.utc)
    await db.flush()


async def _lock_quota_rows_ascending(db: AsyncSession, owner_user_ids: set[int]) -> dict[int, UserMediaQuota]:
    """The single lock-ordering primitive for every code path that touches
    UserMediaQuota: (1) sort owner IDs, (2) create any missing rows via
    INSERT ... ON CONFLICT DO NOTHING (race-safe), (3) lock rows via
    SELECT ... FOR UPDATE in ascending owner_id order. No code path may
    lock a MediaAsset row and then a UserMediaQuota row for the same
    operation — quota, if touched at all, is always locked first."""
    if not owner_user_ids:
        return {}
    sorted_ids = sorted(owner_user_ids)
    await db.execute(
        insert(UserMediaQuota)
        .values([
            {"user_id": uid, "file_count": 0, "total_bytes": 0, "daily_bytes": 0,
             "daily_window_started_at": datetime.now(timezone.utc)}
            for uid in sorted_ids
        ])
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    rows = (await db.execute(
        select(UserMediaQuota).where(UserMediaQuota.user_id.in_(sorted_ids))
        .order_by(UserMediaQuota.user_id.asc())
        .with_for_update()
    )).scalars().all()
    return {row.user_id: row for row in rows}


async def reserve_upload_quota(db: AsyncSession, *, owner_user_id: int, incoming_file_size_bytes: int) -> None:
    """Only the rolling daily upload-bytes limit is actually enforced this
    round. file_count/total_bytes are still incremented on every successful
    upload (accurate running totals for reporting — see
    find_cleanup_candidates), but this does NOT raise on
    MEDIA_MAX_FILES_PER_USER/MEDIA_MAX_TOTAL_BYTES_PER_USER: with physical
    cleanup out of scope this round, a user who hit a lifetime cap would be
    permanently stuck there. Flush-only, no commit — the operation-level
    caller commits once, after this and every other step has succeeded."""
    quota = (await _lock_quota_rows_ascending(db, {owner_user_id}))[owner_user_id]

    now = datetime.now(timezone.utc)
    if now - quota.daily_window_started_at >= timedelta(hours=24):
        quota.daily_bytes = 0
        quota.daily_window_started_at = now

    if quota.daily_bytes + incoming_file_size_bytes > settings.MEDIA_MAX_DAILY_UPLOAD_BYTES_PER_USER:
        raise HTTPException(429, "Daily upload quota exceeded.")
    # MEDIA_MAX_FILES_PER_USER / MEDIA_MAX_TOTAL_BYTES_PER_USER are deliberately
    # NOT enforced here this round — tracked only, below.

    quota.file_count += 1
    quota.total_bytes += incoming_file_size_bytes
    quota.daily_bytes += incoming_file_size_bytes
    await db.flush()


async def mark_media_superseded(db: AsyncSession, *, storage_key: str) -> None:
    """Avatar/cover replacement: transitions the OLD asset to
    DELETION_PENDING (logical deletion only — the physical file still
    exists, cleanup is dry-run only this round). Does NOT touch
    UserMediaQuota: releasing quota here would let a user log a file as
    'deleted' and immediately regain upload capacity while the bytes are
    still on disk. No-op if no MediaAsset row exists for this key (predates
    tracking — compatibility case) or if it's already DELETION_PENDING
    (idempotent). Never calls storage_provider.delete_file — dry-run-only
    boundary holds regardless. Flush-only, no commit."""
    asset = await db.scalar(
        select(MediaAsset)
        .where(MediaAsset.storage_key == storage_key, MediaAsset.status != MediaAssetStatus.DELETION_PENDING)
        .with_for_update()
    )
    if asset is None:
        return
    asset.status = MediaAssetStatus.DELETION_PENDING
    asset.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def mark_media_deleted_for_posts(db: AsyncSession, *, post_ids: list[int]) -> int:
    """Same logical-deletion-only behavior as mark_media_superseded — no
    quota decrement. Locks target MediaAsset rows via a single batched
    SELECT ... FOR UPDATE with an explicit ORDER BY id ASC, so two
    concurrent post-deletion closures touching overlapping asset sets in
    different discovery orders can't deadlock against each other.
    Idempotent (status != DELETION_PENDING guard) and legacy-tolerant
    (posts with no tracked row are silently skipped — post deletion must
    never fail because tracking metadata doesn't exist for a pre-migration
    file)."""
    target_ids = (await db.scalars(
        select(MediaAsset.id)
        .where(MediaAsset.attached_to_type == "post", MediaAsset.attached_to_id.in_(post_ids),
               MediaAsset.status != MediaAssetStatus.DELETION_PENDING)
        .order_by(MediaAsset.id.asc())
        .with_for_update()
    )).all()
    if not target_ids:
        return 0

    await db.execute(
        update(MediaAsset).where(MediaAsset.id.in_(target_ids))
        .values(status=MediaAssetStatus.DELETION_PENDING, deleted_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return len(target_ids)


async def write_media_to_storage_and_flush(
    db: AsyncSession, *, owner_user_id: int, media_type: MediaAssetType, content: bytes, content_type: str,
    storage_provider=None, original_filename: str | None = None,
) -> MediaAsset:
    """Writes the file to storage, then reserves quota and registers the
    PENDING MediaAsset row via flush (not commit) inside whatever
    transaction the caller's session is already participating in — this
    function does not own the transaction.

    `storage_provider` defaults to the standard get_storage_provider()
    instance; pass an explicit one for surfaces that use a different
    physical location (e.g. feedback attachments, which write to
    FEEDBACK_ATTACHMENT_LOCAL_DIR via a differently-configured
    LocalStorageProvider, not the default upload directory) — the SAME
    instance must then be passed to run_media_operation's own
    storage_provider so compensation targets the right location.

    On any failure AFTER the storage write (quota exceeded, flush error),
    the file just written (storage_key is a freshly-generated UUID, so this
    can never touch a pre-existing file) is compensating-deleted right
    here, and the exception is re-raised WITHOUT rolling back the session —
    rollback is the operation-level caller's responsibility (see
    run_media_operation). If the compensating delete itself also fails, a
    structured, searchable log line records the orphan for manual/future
    repair instead of silently losing track of it."""
    storage_provider = storage_provider or get_storage_provider()
    stored = await storage_provider.save_file(
        content=content, content_type=content_type, original_filename=original_filename,
    )
    try:
        await reserve_upload_quota(db, owner_user_id=owner_user_id, incoming_file_size_bytes=len(content))
        asset = await register_pending_media(
            db, owner_user_id=owner_user_id, media_type=media_type,
            storage_key=stored.storage_key, content_type=content_type, file_size_bytes=len(content),
        )
        return asset
    except Exception:
        try:
            await storage_provider.delete_file(storage_key=stored.storage_key)
        except Exception:
            logger.error(
                "media_orphan_repair_needed",
                extra={"storage_key": stored.storage_key, "owner_user_id": owner_user_id},
                exc_info=True,
            )
        raise
    # Note: "database success followed by storage failure" is not applicable given this
    # storage-write-then-DB-registration ordering — that sequence cannot occur through this
    # path by construction, so no test is written for it.


async def run_media_operation(db: AsyncSession, fn, *, storage_provider=None):
    """The single transaction-ownership pattern every route/service in this
    module uses, instead of any low-level helper committing on its own.
    `fn` is an async callable taking one argument, `compensation: list[str]`,
    to which it must append each newly-written storage_key as soon as the
    write that produced it has succeeded.

    `storage_provider` defaults to the standard get_storage_provider()
    instance — pass the SAME explicit provider given to
    write_media_to_storage_and_flush within `fn` when that call used a
    non-default one (e.g. feedback attachments), so compensation targets
    the correct physical location.

    A pre-commit failure (fn itself raises) is DEFINITE: nothing was
    persisted, so this wrapper rolls back and compensating-deletes every
    key in `compensation` immediately.

    A commit exception is INDETERMINATE, not a proven failure — it does not
    prove the transaction failed to land server-side (e.g. a dropped
    connection after COMMIT was sent but before the ack came back).
    Blindly compensating-deleting in that case risks deleting a file whose
    MediaAsset row DID get committed. So on a commit exception specifically,
    this wrapper does NOT delete any file — it logs
    `media_commit_outcome_unknown` and leaves resolution to a future,
    separately-built reconciliation pass using a fresh session."""
    storage_provider = storage_provider or get_storage_provider()
    compensation: list[str] = []
    try:
        result = await fn(compensation)
    except Exception:
        await db.rollback()
        for storage_key in compensation:
            try:
                await storage_provider.delete_file(storage_key=storage_key)
            except Exception:
                logger.error(
                    "media_orphan_repair_needed",
                    extra={"storage_key": storage_key},
                    exc_info=True,
                )
        raise

    try:
        await db.commit()
    except Exception:
        logger.error(
            "media_commit_outcome_unknown",
            extra={"storage_keys": list(compensation)},
            exc_info=True,
        )
        raise
    return result


@dataclass(frozen=True)
class ExpiredPendingAsset:
    id: int
    owner_user_id: int
    storage_key: str
    created_at: datetime


@dataclass(frozen=True)
class OrphanedDeletedAsset:
    id: int
    owner_user_id: int
    storage_key: str
    deleted_at: datetime | None


@dataclass(frozen=True)
class OverLifetimeLimitUser:
    user_id: int
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class MediaCleanupReport:
    """DRY-RUN ONLY report — no mutation, no storage calls, ever. Callers
    (the CLI script) may only print this; nothing in this module performs
    real deletion. Physical file removal is a separate, future,
    explicitly-approved feature."""
    generated_at: datetime
    expired_pending: list[ExpiredPendingAsset] = field(default_factory=list)
    orphaned_deletion_pending: list[OrphanedDeletedAsset] = field(default_factory=list)
    users_over_lifetime_limits: list[OverLifetimeLimitUser] = field(default_factory=list)


async def find_cleanup_candidates(db: AsyncSession, *, now: datetime | None = None) -> MediaCleanupReport:
    """DRY-RUN ONLY — read-only queries, no mutation, no storage calls.

    Reports PENDING assets older than MEDIA_PENDING_EXPIRATION_HOURS and
    DELETION_PENDING assets (this round's 'logical deletion, physical file
    still on disk' state) in separate, clearly labeled buckets —
    DELETION_PENDING assets are not 'safe to fully forget': their
    storage_key is still a real file on disk that a future physical-
    deletion feature would need to actually remove (and, at that point,
    decrement quota for) — this only ever reports that fact.

    Also reports every user whose current file_count or total_bytes
    already exceeds the proposed (not-yet-enforced) MEDIA_MAX_FILES_PER_USER
    / MEDIA_MAX_TOTAL_BYTES_PER_USER limits, so ops has concrete data before
    ever flipping enforcement on.

    Scope note: UserMediaQuota only reflects uploads made through this
    feature. Pre-migration legacy files (existing avatar/cover/post images/
    feedback attachments with no MediaAsset row) are not counted in any
    user's quota totals and are not enumerated by this report — it only
    ever describes tracked, MediaAsset-backed rows."""
    now = now or datetime.now(timezone.utc)
    expiration_cutoff = now - timedelta(hours=settings.MEDIA_PENDING_EXPIRATION_HOURS)

    expired_pending_rows = (await db.execute(
        select(MediaAsset)
        .where(MediaAsset.status == MediaAssetStatus.PENDING, MediaAsset.created_at < expiration_cutoff)
        .order_by(MediaAsset.id.asc())
    )).scalars().all()

    orphaned_rows = (await db.execute(
        select(MediaAsset)
        .where(MediaAsset.status == MediaAssetStatus.DELETION_PENDING)
        .order_by(MediaAsset.id.asc())
    )).scalars().all()

    over_limit_rows = (await db.execute(
        select(UserMediaQuota)
        .where(
            (UserMediaQuota.file_count > settings.MEDIA_MAX_FILES_PER_USER)
            | (UserMediaQuota.total_bytes > settings.MEDIA_MAX_TOTAL_BYTES_PER_USER)
        )
        .order_by(UserMediaQuota.user_id.asc())
    )).scalars().all()

    return MediaCleanupReport(
        generated_at=now,
        expired_pending=[
            ExpiredPendingAsset(
                id=row.id, owner_user_id=row.owner_user_id,
                storage_key=row.storage_key, created_at=row.created_at,
            )
            for row in expired_pending_rows
        ],
        orphaned_deletion_pending=[
            OrphanedDeletedAsset(
                id=row.id, owner_user_id=row.owner_user_id,
                storage_key=row.storage_key, deleted_at=row.deleted_at,
            )
            for row in orphaned_rows
        ],
        users_over_lifetime_limits=[
            OverLifetimeLimitUser(user_id=row.user_id, file_count=row.file_count, total_bytes=row.total_bytes)
            for row in over_limit_rows
        ],
    )
