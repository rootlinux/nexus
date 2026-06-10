# Security Control Plane V1

## Scope

This document defines the Phase 1 control-plane baseline for the invite-only beta. Invite-only access controls onboarding and growth. It is not a security boundary.

## Roles

- `super_admin`
  Full control-plane access.
- `invite_admin`
  Invite lifecycle control and masked user review.
- `moderator`
  Moderation enforcement and masked user review.
- `support_admin`
  Read-focused support access with masked data and audit visibility.

Existing legacy `is_admin=true` users are treated as `super_admin` until an explicit `admin_role` is assigned.

## Capabilities

- `user.read_basic`
- `user.read_sensitive_masked`
- `invite.create`
- `invite.assign`
- `invite.reveal_full`
- `invite.revoke`
- `moderation.suspend`
- `moderation.ban`
- `role.change`
- `audit.read`

Role mapping in code:

- `super_admin`: all capabilities
- `invite_admin`: `user.read_basic`, `user.read_sensitive_masked`, `invite.create`, `invite.assign`, `invite.reveal_full`, `invite.revoke`, `audit.read`
- `moderator`: `user.read_basic`, `user.read_sensitive_masked`, `moderation.suspend`, `moderation.ban`, `audit.read`
- `support_admin`: `user.read_basic`, `user.read_sensitive_masked`, `audit.read`

## Session Boundary Rules

- Normal user session:
  Authenticated access token plus DB-backed user lookup.
- Admin-sensitive session policy:
  `require_admin_session` enforces authenticated access, DB-backed role resolution, and moderation checks.
- Admin access is never granted from client-side `isAdmin` alone.
- Capability checks are enforced server-side with `require_capability(...)`.
- `enforce_not_banned` blocks banned and suspended users on request handling.
- Refresh flow re-checks moderation state before issuing new tokens.
- Ban and suspend actions revoke active refresh tokens to stop session continuation.
- Logout is idempotent:
  missing, invalid, or already-revoked refresh tokens do not produce a 500.
- Admin bootstrap/reset policy:
  no in-app CLI, startup hook, or hidden runtime path creates or resets admin accounts. Admin identity is established only through seed/init DB state or operator-controlled database procedures outside the app runtime.

## Invite Storage / Reveal Policy

- Current product behavior remains intact:
  assigned invite owners can still view their own assigned invite code in profile.
- Admin surfaces are now masked by default.
- Full admin reveal uses a dedicated audited endpoint and is rate limited.
- Current storage is still plaintext in DB for compatibility with existing UX and local beta flow.
- Direction for next phase:
  move invite code storage to encrypted-at-rest, keep masked-by-default responses, and keep reveal audited.

## Moderation Enforcement Rules

- `banned` users:
  blocked on authenticated requests and blocked on refresh.
- `suspended` users:
  blocked on authenticated requests and blocked on refresh.
- Ban/suspend revokes outstanding refresh tokens.
- Unban/unsuspend restores eligibility for future login/refresh but does not silently restore revoked sessions.
- Admin moderation actions require capability and are audit logged.

## Audit-Required Events

Implemented now:

- `login`
- `logout`
- `invite.create`
- `invite.assign`
- `invite.reveal`
- `invite.redeem`
- `invite.revoke`
- `ban`
- `unban`
- `suspend`
- `unsuspend`

Deferred for later implementation:

- `role.change`
  No role-management endpoint exists yet in this codebase pass.

## Rate-Limited Endpoints

- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/auth/refresh`
- `GET /api/invite/validate`
- `POST /api/invite/create`
- `POST /api/admin/invites/{invite_id}/reveal`

Password reset is not present in the current codebase, so no reset endpoint was added in this pass.

## Code Anchors

- Roles/capabilities: `backend/app/core/authorization.py`
- Auth/session enforcement: `backend/app/api/deps.py`
- Audit model/service: `backend/app/models/admin_audit_log.py`, `backend/app/services/audit.py`
- Auth audit + logout hardening: `backend/app/api/routes/auth.py`
- Invite policy + reveal path: `backend/app/api/routes/invite.py`, `backend/app/api/routes/admin.py`
- Migration: `backend/alembic/versions/009_phase1_control_plane.py`
