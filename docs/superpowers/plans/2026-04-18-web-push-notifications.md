# Web Push Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement end-to-end web push notifications using a dedicated `push_subscriptions` table, backend VAPID delivery, and real browser subscription wiring on the notifications page.

**Architecture:** Extend the existing notification system rather than creating a parallel one. Persist browser subscriptions by unique endpoint, fan out push sends from the existing notification creation helpers when settings allow, and keep the web client and service worker aligned to one compact payload contract.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, web-push library, Next.js, TypeScript, service worker JavaScript, pytest/unittest

---

### Task 1: Add The Failing Backend Tests

**Files:**
- Create: `backend/tests/test_push_notifications.py`
- Inspect: `backend/app/services/notifications.py`
- Inspect: `backend/app/api/routes/notifications.py`

- [ ] **Step 1: Write failing tests for subscription upsert, multi-subscription fan-out, settings gating, and failure cleanup**

```python
async def test_push_subscription_put_upserts_by_endpoint(...): ...
async def test_create_notification_fans_out_to_all_active_subscriptions(...): ...
async def test_push_delivery_respects_notification_settings(...): ...
async def test_push_delivery_deactivates_only_failing_subscription(...): ...
async def test_test_send_route_targets_active_subscriptions(...): ...
```

- [ ] **Step 2: Run the focused backend test file and confirm it fails for missing push subscription behavior**

Run: `cd backend && pytest tests/test_push_notifications.py -q`
Expected: FAIL with missing model, route, schema, or push-delivery implementation errors.

### Task 2: Add Backend Push Persistence And API

**Files:**
- Create: `backend/app/models/push_subscription.py`
- Create: `backend/alembic/versions/033_push_subscriptions_web_push.py`
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/notification.py`
- Modify: `backend/app/api/routes/notifications.py`

- [ ] **Step 1: Add the SQLAlchemy model and user relationship**

```python
class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    ...
```

- [ ] **Step 2: Add the migration with unique `endpoint` and supporting indexes**

Run: `cd backend && alembic upgrade head`
Expected: the new table is created successfully.

- [ ] **Step 3: Add request/response schemas and authenticated CRUD routes**

```python
@router.put("/push-subscriptions", ...)
@router.get("/push-subscriptions", ...)
@router.delete("/push-subscriptions", ...)
@router.post("/push-subscriptions/test-send", ...)
```

- [ ] **Step 4: Re-run the focused tests**

Run: `cd backend && pytest tests/test_push_notifications.py -q`
Expected: earlier route/model failures are replaced by push sender behavior failures.

### Task 3: Add Backend Web Push Delivery

**Files:**
- Create: `backend/app/services/push_notifications.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`
- Modify: `deploy/.env.local-smoke.example`
- Modify: `deploy/.env.docker`
- Modify: `backend/app/services/notifications.py`

- [ ] **Step 1: Add VAPID settings and a web-push sender wrapper**

```python
VAPID_PUBLIC_KEY: str = ""
VAPID_PRIVATE_KEY: str = ""
VAPID_SUBJECT: str = "mailto:..."
```

- [ ] **Step 2: Implement payload building, subscription upsert helpers, fan-out send, and failure deactivation**

```python
async def upsert_push_subscription(...): ...
async def send_push_to_user_subscriptions(...): ...
async def deactivate_push_subscription(...): ...
```

- [ ] **Step 3: Trigger push delivery from the existing notification creation helper after the in-app notification row exists**

```python
notification = await create_notification(...)
await maybe_send_push_notification(...)
```

- [ ] **Step 4: Re-run the focused backend tests**

Run: `cd backend && pytest tests/test_push_notifications.py -q`
Expected: PASS for the new push-notification backend coverage.

### Task 4: Add Frontend Subscription Wiring

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/app/notifications/page.tsx`
- Modify: `web/src/lib/env.ts`

- [ ] **Step 1: Add client API types and endpoints for push subscription CRUD plus VAPID key access**

```ts
export interface PushSubscriptionRecord { ... }
export const upsertPushSubscription = async (...) => { ... }
```

- [ ] **Step 2: Wire the notifications page to detect support, request permission, create the browser subscription, persist it to the backend, and unsubscribe cleanly**

```ts
const supportsWebPush = ...
const handleEnablePush = async () => { ... }
const handleDisablePush = async () => { ... }
```

- [ ] **Step 3: Run lint on the touched frontend files**

Run: `cd web && npm run lint -- src/app/notifications/page.tsx src/lib/api.ts src/types/index.ts src/lib/env.ts`
Expected: PASS with no new lint errors in the touched files.

### Task 5: Align The Service Worker

**Files:**
- Modify: `web/public/sw.js`

- [ ] **Step 1: Align `push` and `notificationclick` handling with the backend payload contract**

```js
self.addEventListener('push', ...)
self.addEventListener('notificationclick', ...)
```

- [ ] **Step 2: Add a focused browser-safe regression test if practical, otherwise verify via manual smoke steps documented in the final report**

Run: `cd web && npm run lint -- public/sw.js`
Expected: PASS if the lint setup covers the worker; otherwise document manual verification.

### Task 6: Final Verification

**Files:**
- Inspect: backend and web touched files

- [ ] **Step 1: Run the backend push test file**

Run: `cd backend && pytest tests/test_push_notifications.py -q`
Expected: PASS

- [ ] **Step 2: Run a broader backend regression slice around notifications**

Run: `cd backend && pytest tests/test_release_blockers.py -q`
Expected: PASS

- [ ] **Step 3: Run frontend lint or build verification for touched files**

Run: `cd web && npm run lint`
Expected: PASS or a clearly documented pre-existing issue if unrelated failures exist.

- [ ] **Step 4: Capture final changed files**

Run: `git status --short`
Expected: only the planned push-notification artifacts and implementation files are changed.
