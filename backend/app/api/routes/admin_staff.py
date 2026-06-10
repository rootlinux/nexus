from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin_session
from app.core.database import get_db
from app.models.staff_permission import StaffPermission, StaffRole
from app.models.user import User
from app.schemas.staff import (
    StaffActorRead,
    StaffAssignmentCreate,
    StaffAssignmentListResponse,
    StaffAssignmentRead,
    StaffAssignmentRemove,
    StaffAssignmentUpdate,
    StaffPermissionRead,
    StaffUserSummary,
)
from app.services.audit import write_audit_log
from app.services.admin_security import revoke_all_refresh_tokens_for_user
from app.services.staff_permissions import (
    PHASE1_EDITABLE_PERMISSION_FIELDS,
    apply_staff_permission_updates,
    build_staff_defaults,
    enforce_staff_assignment_permissions,
    get_staff_role_rank,
    get_staff_permission_record,
    resolve_staff_role,
    serialize_staff_permissions,
    staff_has_permission,
)

router = APIRouter(prefix="/admin/staff", tags=["admin"])


def _manageable_roles_for_actor(actor: User) -> list[StaffRole]:
    actor_role = resolve_staff_role(actor)
    if actor_role == StaffRole.SUPER_ADMIN:
        return [StaffRole.ADMIN, StaffRole.MODERATOR]
    if actor_role == StaffRole.ADMIN:
        return [StaffRole.MODERATOR]
    return []


def _staff_assignment_to_response(staff_permission: StaffPermission, actor: User) -> StaffAssignmentRead:
    actor_role = resolve_staff_role(actor)
    target_role = staff_permission.role
    can_manage_target = (
        actor_role is not None
        and staff_has_permission(actor, "can_manage_moderators")
        and actor.id != staff_permission.user_id
        and get_staff_role_rank(actor_role) > get_staff_role_rank(target_role)
    )

    return StaffAssignmentRead(
        id=staff_permission.id,
        user=StaffUserSummary(
            user_id=staff_permission.user.id,
            username=staff_permission.user.username,
            display_name=staff_permission.user.display_name,
            email=staff_permission.user.email,
        ),
        permissions=StaffPermissionRead(**serialize_staff_permissions(staff_permission)),
        updated_by_user_id=staff_permission.updated_by_user_id,
        updated_by_username=staff_permission.updated_by_user.username if staff_permission.updated_by_user else None,
        created_at=staff_permission.created_at,
        updated_at=staff_permission.updated_at,
        can_edit=can_manage_target,
        can_remove=can_manage_target,
    )


async def _get_user_by_identifier(db: AsyncSession, payload: StaffAssignmentCreate) -> User:
    if payload.user_id is None and payload.username is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either user_id or username is required",
        )

    query = select(User).options(selectinload(User.staff_permission))
    if payload.user_id is not None:
        query = query.where(User.id == payload.user_id)
    else:
        query = query.where(User.username == payload.username)

    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("", response_model=StaffAssignmentListResponse)
async def list_staff_assignments(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    if not staff_has_permission(current_admin, "can_manage_moderators"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this action")

    result = await db.execute(
        select(StaffPermission)
        .options(
            selectinload(StaffPermission.user),
            selectinload(StaffPermission.updated_by_user),
        )
        .order_by(StaffPermission.role.asc(), StaffPermission.updated_at.desc(), StaffPermission.id.desc())
    )
    items = result.scalars().all()

    actor_staff_permission = get_staff_permission_record(current_admin)
    if actor_staff_permission is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin session required")

    return StaffAssignmentListResponse(
        current_actor=StaffActorRead(
            user_id=current_admin.id,
            role=actor_staff_permission.role,
            permissions=StaffPermissionRead(**serialize_staff_permissions(actor_staff_permission)),
            manageable_roles=_manageable_roles_for_actor(current_admin),
        ),
        items=[_staff_assignment_to_response(item, current_admin) for item in items],
    )


@router.post("", response_model=StaffAssignmentRead, status_code=status.HTTP_201_CREATED)
async def create_staff_assignment(
    request: Request,
    payload: StaffAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    target_user = await _get_user_by_identifier(db, payload)
    existing_staff_permission = get_staff_permission_record(target_user)
    if existing_staff_permission is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already has a staff assignment")

    enforce_staff_assignment_permissions(
        current_admin,
        target_user=target_user,
        desired_role=payload.role,
        existing_staff_permission=None,
    )

    staff_permission = StaffPermission(user_id=target_user.id)
    apply_staff_permission_updates(
        staff_permission,
        role=payload.role,
        invite_quota_monthly=(payload.permissions.invite_quota_monthly if payload.permissions else build_staff_defaults(payload.role)["invite_quota_monthly"]),
        updates=(payload.permissions.model_dump() if payload.permissions else {}),
        updated_by_user_id=current_admin.id,
    )
    db.add(staff_permission)
    await db.flush()

    target_user.staff_permission = staff_permission
    await revoke_all_refresh_tokens_for_user(db, target_user.id)

    await write_audit_log(
        db,
        action="moderator_added",
        actor_user=current_admin,
        target_type="user",
        target_id=target_user.id,
        after={
            "user_id": target_user.id,
            "username": target_user.username,
            "staff_permissions": serialize_staff_permissions(staff_permission),
        },
        request=request,
        success=True,
    )
    await db.commit()

    refreshed = await db.execute(
        select(StaffPermission)
        .options(selectinload(StaffPermission.user), selectinload(StaffPermission.updated_by_user))
        .where(StaffPermission.id == staff_permission.id)
    )
    return _staff_assignment_to_response(refreshed.scalar_one(), current_admin)


@router.put("/{staff_permission_id}", response_model=StaffAssignmentRead)
async def update_staff_assignment(
    request: Request,
    staff_permission_id: int,
    payload: StaffAssignmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    result = await db.execute(
        select(StaffPermission)
        .options(selectinload(StaffPermission.user), selectinload(StaffPermission.updated_by_user))
        .where(StaffPermission.id == staff_permission_id)
    )
    staff_permission = result.scalar_one_or_none()
    if staff_permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff assignment not found")

    before = serialize_staff_permissions(staff_permission)
    enforce_staff_assignment_permissions(
        current_admin,
        target_user=staff_permission.user,
        desired_role=payload.role,
        existing_staff_permission=staff_permission,
    )

    updates = {
        field_name: getattr(payload.permissions, field_name)
        for field_name in PHASE1_EDITABLE_PERMISSION_FIELDS
    }
    apply_staff_permission_updates(
        staff_permission,
        role=payload.role,
        invite_quota_monthly=payload.permissions.invite_quota_monthly,
        updates=updates,
        updated_by_user_id=current_admin.id,
    )
    after = serialize_staff_permissions(staff_permission)
    if before != after:
        await revoke_all_refresh_tokens_for_user(db, staff_permission.user_id)
    await write_audit_log(
        db,
        action="staff_permissions_updated",
        actor_user=current_admin,
        target_type="user",
        target_id=staff_permission.user_id,
        before=before,
        after=after,
        reason=payload.reason,
        request=request,
        success=True,
    )
    await db.commit()

    refreshed = await db.execute(
        select(StaffPermission)
        .options(selectinload(StaffPermission.user), selectinload(StaffPermission.updated_by_user))
        .where(StaffPermission.id == staff_permission.id)
    )
    return _staff_assignment_to_response(refreshed.scalar_one(), current_admin)


@router.delete("/{staff_permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_staff_assignment(
    request: Request,
    staff_permission_id: int,
    payload: StaffAssignmentRemove,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin_session),
):
    result = await db.execute(
        select(StaffPermission)
        .options(selectinload(StaffPermission.user))
        .where(StaffPermission.id == staff_permission_id)
    )
    staff_permission = result.scalar_one_or_none()
    if staff_permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff assignment not found")

    enforce_staff_assignment_permissions(
        current_admin,
        target_user=staff_permission.user,
        desired_role=None,
        existing_staff_permission=staff_permission,
    )

    before = serialize_staff_permissions(staff_permission)
    target_user = staff_permission.user
    await write_audit_log(
        db,
        action="moderator_removed",
        actor_user=current_admin,
        target_type="user",
        target_id=target_user.id,
        before=before,
        reason=payload.reason,
        request=request,
        success=True,
    )
    await db.delete(staff_permission)
    await revoke_all_refresh_tokens_for_user(db, target_user.id)
    await db.commit()
