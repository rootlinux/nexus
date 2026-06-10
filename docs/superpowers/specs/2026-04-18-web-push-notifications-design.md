# Web Push Notifications Design

**Date:** 2026-04-18

## Goal

Add production-minded web push notifications to the existing notification system without breaking current in-app notification behavior. The system must support one user to many active browser/device subscriptions, upsert subscriptions by endpoint, fan out delivery to all active subscriptions, and deactivate only the failing subscription when delivery proves it is no longer valid.

## Scope

- Add a dedicated backend `push_subscriptions` table and SQLAlchemy model.
- Add authenticated backend CRUD endpoints under `/api/notifications/push-subscriptions`.
- Add an authenticated push smoke-test send route.
- Add VAPID configuration and backend send helpers.
- Trigger push as a side effect of the existing notification creation service, gated by existing notification settings.
- Wire the notifications page to create, refresh, persist, and delete real browser subscriptions through the backend.
- Keep the current service worker registration path and extend the existing service worker behavior only as needed.
- Add backend and frontend tests that make end-to-end delivery behavior testable.

## Non-Goals

- No full device registry.
- No unrelated notification UX redesign.
- No replacement of in-app notifications with push-only behavior.
- No change to app domains, branding, or unrelated PWA caching behavior.

## Existing System

The repo already has:

- `notifications` and `notification_settings` models
- `/api/notifications` list/read/settings routes
- notification creation helpers in `backend/app/services/notifications.py`
- service worker registration in `web/src/components/PwaBoot.tsx`
- push and `notificationclick` listeners already started in `web/public/sw.js`
- a notifications page with browser permission UI and notification settings toggles

What is missing is persistence of real push subscriptions, a backend send pipeline, and client wiring that makes the current notifications UI real instead of browser-permission-only.

## Data Model

Add `push_subscriptions` with:

- `id`
- `user_id`
- `endpoint` unique
- `p256dh`
- `auth`
- `user_agent` nullable
- `last_seen_at`
- `last_success_at` nullable
- `last_failure_at` nullable
- `is_active`
- `created_at`
- `updated_at`

Design choices:

- `endpoint` is globally unique and acts as the upsert identity.
- A user may own many subscriptions across browsers and devices.
- A subscription can move between users if the same browser endpoint is re-registered after account switching; the upsert path should attach the endpoint to the authenticated user that owns the current registration.
- Delivery failure cleanup touches only the failing row so healthy subscriptions continue to receive push.

## Backend API Design

Under `/api/notifications/push-subscriptions`:

- `GET /api/notifications/push-subscriptions`
  Returns the current user’s subscriptions.
- `PUT /api/notifications/push-subscriptions`
  Upserts a subscription by `endpoint` using the current authenticated user and submitted keys.
- `DELETE /api/notifications/push-subscriptions`
  Deletes or deactivates a subscription identified by `endpoint`.
- `POST /api/notifications/push-subscriptions/test-send`
  Sends a smoke-test push to the user’s active subscriptions, with optional endpoint targeting if needed for focused debugging.

The API remains minimal and authenticated. The frontend uses `PUT` for both first registration and refresh/update so duplicate rows are not created.

## Delivery Pipeline

Push delivery becomes an additional side effect of real notification creation:

1. Existing helper creates the in-app `Notification` row.
2. The helper checks the recipient’s `NotificationSettings` using the existing `push_*` booleans mapped from notification type.
3. If push is enabled for that type, the service builds a small payload from the created notification and sends it to all active subscriptions for that recipient.
4. Successful sends update `last_success_at`.
5. Known invalid/expired send failures mark only that subscription inactive and update `last_failure_at`.

This keeps the in-app notification system as the source of truth and avoids a fake parallel pipeline.

## Payload Shape

Backend sends a compact JSON payload aligned with the current service worker:

- `title`
- `body`
- `url`
- `tag` optional
- `icon` optional
- `badge` optional
- `notification_id`
- `notification_type`

`url` should route to the same destination users would reach from the in-app notification list, usually a post detail URL with the existing notification reentry query params, falling back to the actor profile or `/notifications`.

## Frontend Flow

Notifications page behavior:

1. Detect support using `Notification`, `serviceWorker`, and `PushManager`.
2. Show unsupported, denied, granted-not-subscribed, and subscribed states.
3. Request permission only on explicit user action.
4. Register or await the existing service worker.
5. Create or refresh a `PushSubscription` using the backend VAPID public key.
6. Send the subscription to the backend upsert endpoint with browser `userAgent`.
7. Reflect actual backend-backed subscription state in the UI.
8. Allow unsubscribe by removing the browser subscription and calling the backend delete endpoint.

If Push API is unsupported, the page must clearly communicate that in-app notifications still work while system push is unavailable on that browser.

## Service Worker Behavior

Keep the current `web/public/sw.js` as the source of truth and align it with the backend payload:

- Parse JSON safely in `push`.
- Show a notification with sensible default title/body/icon/badge.
- Store the target URL in `data.url`.
- On `notificationclick`, focus an existing client when possible, navigate it to the target URL, otherwise open a new window.

This stays minimal and avoids introducing a framework-specific worker build step.

## Testing Strategy

Backend tests:

- subscription upsert by endpoint
- multi-subscription list and delete behavior
- fan-out send to all active subscriptions
- settings-gated push delivery
- invalid subscription failure deactivation
- smoke-test send route behavior

Frontend/browser tests:

- notifications page capability state logic where practical
- service worker `notificationclick` URL behavior

Because browser push transport is hard to prove in CI without a real push service, backend send helpers should be structured for unit/integration tests with a mocked web-push sender. The smoke-test route plus service worker payload contract make end-to-end local verification practical.

## Risks And Mitigations

- Push transport failures from stale endpoints:
  Mitigation: deactivate only the failing subscription and preserve others.
- Browser support differences:
  Mitigation: explicit unsupported/denied/granted/subscribed states in UI.
- Breaking in-app notifications:
  Mitigation: push is attached after normal notification creation, not instead of it.
- Overbuilding device management:
  Mitigation: keep only subscription-level persistence and no separate device table.
