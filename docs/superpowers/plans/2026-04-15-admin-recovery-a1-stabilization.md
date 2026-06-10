# Admin Recovery A1 Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three confirmed admin WebAuthn recovery operability blockers without broadening scope or weakening admin security.

**Architecture:** Add regression coverage for the exact failure boundaries first, then make the smallest safe backend changes at the model/runtime and dependency boundaries, and finally wire the recovery env vars into the standard compose stack with fail-closed defaults preserved.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest/unittest, Docker Compose

---

### Task 1: Reproduce the two backend failure classes in tests

**Files:**
- Modify: `backend/tests/test_webauthn_auth_source_of_truth.py`
- Modify: `backend/tests/test_privileged_session_mfa_enforcement.py`

- [ ] **Step 1: Add a regression test for recovery registration persistence shape**
  Assert recovery registration persists a `WebAuthnCredential` with timezone-aware timestamps and does not mint an admin session.

- [ ] **Step 2: Add a regression test for admin dependency rejection of non-session JWTs**
  Assert `require_admin_session` returns a clean auth error when a bearer token lacks a DB-backed session id instead of dereferencing `None`.

- [ ] **Step 3: Run the targeted tests to watch them fail for the current bug class**
  Run: `pytest backend/tests/test_webauthn_auth_source_of_truth.py backend/tests/test_privileged_session_mfa_enforcement.py -q`

### Task 2: Fix the recovery registration persistence boundary

**Files:**
- Modify: `backend/app/models/webauthn_credential.py`
- Create: `backend/alembic/versions/030_webauthn_credential_timestamp_timezone_fix.py`

- [ ] **Step 1: Align the SQLAlchemy model to timezone-aware UTC datetimes**
  Change the affected WebAuthn credential datetime columns to `DateTime(timezone=True)` with UTC-aware defaults.

- [ ] **Step 2: Add a narrow migration for the same WebAuthn credential datetime fields**
  Convert only the recovery-complete persistence fields using `AT TIME ZONE 'UTC'` so existing rows remain valid.

### Task 3: Fix the admin dependency robustness boundary

**Files:**
- Modify: `backend/app/api/deps.py`

- [ ] **Step 1: Reject non-session tokens before MFA/session dereference**
  Treat missing session-backed state as invalid credentials for admin routes instead of accessing `active_session.mfa_satisfied`.

- [ ] **Step 2: Keep existing staff and MFA enforcement intact**
  Leave the current admin/staff checks in place after the session presence check.

### Task 4: Wire the recovery env vars into the live-like stack

**Files:**
- Modify: `deploy/docker-compose.yml`

- [ ] **Step 1: Pass through the recovery env vars explicitly**
  Add `ENABLE_ADMIN_WEBAUTHN_RECOVERY` and `ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER` to the backend service environment.

- [ ] **Step 2: Preserve fail-closed defaults**
  Keep the feature disabled by default and leave the identifier empty unless explicitly configured.

### Task 5: Verify only the intended behaviors changed

**Files:**
- Review only

- [ ] **Step 1: Run focused tests and migration sanity checks**
  Run: `pytest backend/tests/test_webauthn_auth_source_of_truth.py backend/tests/test_privileged_session_mfa_enforcement.py -q`

- [ ] **Step 2: Inspect the compose diff and modified backend files**
  Run: `git diff -- backend/app/api/deps.py backend/app/models/webauthn_credential.py backend/alembic/versions/030_webauthn_credential_timestamp_timezone_fix.py backend/tests/test_webauthn_auth_source_of_truth.py backend/tests/test_privileged_session_mfa_enforcement.py deploy/docker-compose.yml`
