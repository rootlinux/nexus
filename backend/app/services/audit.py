from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog
from app.services.staff_permissions import resolve_staff_role


def _get_ip_address(request: Request | None) -> str | None:
    if request is None:
        return None
    if request.client:
        return request.client.host
    return None


async def write_audit_log(
    db: AsyncSession,
    *,
    action: str,
    actor_user=None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request: Request | None = None,
    session_id: str | int | None = None,
    success: bool = True,
) -> AdminAuditLog:
    role = resolve_staff_role(actor_user)
    audit_log = AdminAuditLog(
        actor_user_id=getattr(actor_user, "id", None),
        actor_role=role.value if role else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        before_json=before,
        after_json=after,
        reason=reason,
        request_id=getattr(getattr(request, "state", None), "request_id", None),
        ip_address=_get_ip_address(request),
        user_agent=request.headers.get("user-agent") if request else None,
        session_id=str(session_id) if session_id is not None else None,
        success=success,
    )
    db.add(audit_log)
    await db.flush()
    return audit_log
