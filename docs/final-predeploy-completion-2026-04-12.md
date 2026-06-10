# Final Predeploy Completion Pack

Date: 2026-04-12

Status: predeploy only, do not deploy from this document alone

This document is the operator-facing source of truth for the final combined Lukeyz production deploy pass. It captures the last pre-live hardening state, the canonical sources that should be trusted, the exact post-deploy manual verification pack, and the exact smoke order.

## 1. Canonical Source Of Truth

- Backend test environment:
  `backend/.venv`
  Bootstrap script: `backend/scripts/bootstrap_test_env.sh`
  Targeted test runner: `backend/scripts/run_targeted_security_tests.sh`
- Web manifest:
  `web/src/app/manifest.ts`
  Runtime path expected after build: `/manifest.webmanifest`
- Service worker:
  `web/public/sw.js`
  Registration path expected after build: `/sw.js`
- Feedback attachment path model:
  private local storage root is `backend/feedback_private_uploads` via `FEEDBACK_ATTACHMENT_LOCAL_DIR`
  signed access route prefix is `/api/feedback/attachments` via `FEEDBACK_ATTACHMENT_URL_PREFIX`
  legacy public-style `/uploads/feedback/*` access is intentionally blocked in `backend/app/main.py`
- Local production-like deploy path:
  `deploy/docker-compose.yml`
  local hostnames are `app.x.localtest.me` and `api.x.localtest.me`
- Production hostnames:
  web: `https://linusx.xyz`
  api: `https://api.linusx.xyz`

## 2. Expected Post-Deploy Web Headers

These are the expected web responses after the final deploy. Verify them against the live hostname before any invite or user activity.

- For `https://linusx.xyz/` and normal HTML routes:
  `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
  `X-Frame-Options: DENY`
  `X-Content-Type-Options: nosniff`
  `Referrer-Policy: strict-origin-when-cross-origin`
  `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`
  `Content-Security-Policy: default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'none'; frame-src 'none'; manifest-src 'self'; worker-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://api.linusx.xyz; media-src 'self' blob: https://api.linusx.xyz; font-src 'self' data:; connect-src 'self' https://api.linusx.xyz`
- For `https://linusx.xyz/messages`, `/notifications`, `/admin`, `/auth`, `/login`, `/register`, `/security`, `/bookmarks`, `/invites`:
  all headers above, plus `Cache-Control: no-store`
- For `https://linusx.xyz/manifest.webmanifest`:
  all headers above, plus `Cache-Control: public, max-age=0, must-revalidate`
- For `https://linusx.xyz/sw.js`:
  all headers above, plus `Cache-Control: no-cache, no-store, must-revalidate`

If the production `NEXT_PUBLIC_API_BASE_URL` changes, the CSP `connect-src`, `img-src`, and `media-src` values must be updated to the actual production API origin before deploy.

## 3. Final Manual Inbox / Device Verification Pack

Run this immediately after health and header checks pass.

### Verification Email

1. Create a fresh non-admin account through the real production web hostname.
2. Confirm the verification email arrives in the expected inbox.
3. Confirm sender name and sender address are correct.
4. Confirm the CTA button and fallback URL both point to `https://linusx.xyz/auth/verify-email?...`.
5. Open the email on iPhone Mail and desktop browser.
6. Complete verification.
7. Confirm the token is accepted once and a second reuse is rejected or neutralized safely.

Blocker:
no email, wrong hostname, broken CTA, token failure, or repeatable server error.

### Password Reset Email

1. Request password reset for the same real account.
2. Confirm the reset email arrives in the expected inbox.
3. Confirm the CTA button and fallback URL both point to `https://linusx.xyz/auth/reset-password?...`.
4. Complete the password reset in browser.
5. Confirm login succeeds with the new password and fails with the old one.
6. Confirm the reset token cannot be reused.

Blocker:
no email, wrong hostname, broken reset completion, or token reuse works.

### Feedback Email

1. Sign in as a normal user on production web.
2. Open the feedback/report problem flow.
3. Submit one report without attachment.
4. Submit one report with a valid image attachment.
5. Confirm the feedback destination inbox receives both reports.
6. Confirm the report body includes the expected operator context:
   title, description, path or URL, username, device info, occurred time.
7. For the attachment case, open the signed attachment URL from the email and confirm it works while signed.
8. Confirm there is no public `/uploads/feedback/...` path serving the file.

Blocker:
feedback mail missing, attachment inaccessible through signed URL, or attachment reachable through a legacy public path.

### iPhone / Browser / PWA Check

1. Open `https://linusx.xyz` in iPhone Safari.
2. Confirm the site loads without mixed-content or CSP errors.
3. Add to Home Screen.
4. Confirm the installed icon is the Lukeyz mark and the app name is `Lukeyz`.
5. Launch the installed PWA and confirm login, feed, profile, notifications, and messages open correctly.
6. Put the PWA in background, reopen it, and confirm the session is still coherent.
7. In desktop Chrome or Safari, confirm the web app still loads normally and no obvious header/CSP regressions appear in devtools.

Blocker:
PWA install broken, old branding appears, major layout failure on iPhone, or core authenticated routes fail in standalone mode.

### Admin Mobile Reachability

1. On a mobile browser, sign in with the real admin account.
2. Complete MFA.
3. Confirm admin page loads over the production hostname.
4. Confirm moderation queue and invite/admin surfaces are reachable enough for urgent operator use.
5. Confirm no critical admin route is unusable because of viewport, auth, or CSP breakage.

Blocker:
admin cannot log in on mobile, MFA cannot complete, or critical moderation/admin views are unreachable.

### Normal User Core Flow

1. Register or sign in as a normal user.
2. Verify email if the account is fresh.
3. Load feed.
4. Create a text post.
5. Create a post with image upload.
6. Reply to a post.
7. Like and bookmark a post.
8. Open search and a profile page.
9. Open notifications and click through into a post detail page.
10. Open messages, send a DM, reload, and confirm persistence.
11. Log out and log back in.

Blocker:
auth/session failure, post write failure, upload failure, DM failure, or notification click-through breakage.

### Admin MFA Flow

1. Start from signed-out state.
2. Log in with the admin account on `https://linusx.xyz/auth`.
3. Confirm the MFA step appears when expected.
4. Complete WebAuthn MFA.
5. Open `/admin`.
6. Perform one safe read-heavy admin check:
   moderation queue open, users list open, invite list open.
7. Confirm logout works and a fresh login still requires MFA.

Blocker:
MFA bypass, MFA failure for a valid device, or admin access not gated correctly.

## 4. Exact Final Combined Deploy And Smoke Sequence

This is the only acceptable order for the final combined production deploy pass.

### A. Pre-Sync Freeze

1. Confirm no more feature or redesign work is entering the release.
2. Confirm the repo state includes this predeploy pass and nothing intentionally deferred is undocumented.
3. Confirm the production env values are ready, especially:
   `NEXT_PUBLIC_API_BASE_URL=https://api.linusx.xyz`
   `APP_ENV=production`
   `CORS_ALLOWED_ORIGINS=https://linusx.xyz`
   `ALLOWED_HOSTS=api.linusx.xyz`
   `TRUST_PROXY_HEADERS=true`
   `TRUSTED_PROXY_CIDRS=<real trusted upstream CIDRs>`
   `REFRESH_COOKIE_SECURE=true`

### B. Sync

1. Sync the full repo state used for release to the production host.
2. Sync `web/`, `backend/`, `deploy/`, and `docs/` together so config and runbooks match the code.
3. Confirm the production host has the final env file intended for this release.

### C. Build / Rebuild

1. `docker compose -f deploy/docker-compose.yml config`
2. `docker compose -f deploy/docker-compose.yml build backend web`
3. `docker compose -f deploy/docker-compose.yml up -d`
4. `docker compose -f deploy/docker-compose.yml ps`
5. `docker compose -f deploy/docker-compose.yml logs --tail=200 backend web`

### D. Verify First

1. `curl -fsS https://api.linusx.xyz/health`
2. `curl -i https://api.linusx.xyz/ready`
3. `curl -I https://linusx.xyz/`
4. `curl -I https://linusx.xyz/manifest.webmanifest`
5. `curl -I https://linusx.xyz/sw.js`
6. Confirm the expected web headers from Section 2.
7. Confirm the API still returns security headers and that `/ready` is not `503`.

### E. Verify Second

1. Run the manual inbox/device verification pack from Section 3.
2. Run the normal user core flow before any admin-only checks are treated as sufficient.
3. Run the admin MFA flow.
4. Run the admin mobile reachability check.

### F. Blocker Rules

Immediate blockers:

- `GET /ready` fails or returns `503`
- backend or web crash-loop
- CSP/header regression that blocks normal product use
- verification or password-reset emails fail
- feedback email fails
- attachment privacy regression
- normal-user auth/session/core-post/DM flow fails
- admin MFA is bypassed or broken
- moderation/admin reachability is broken for urgent operator use

### G. Acceptable Non-Blocking Gaps

These are only acceptable if they are cosmetic, reproducible, documented, and do not affect security, auth, messaging, moderation, or deploy recovery.

- minor icon crop or splash polish issue with no functional impact
- minor mobile layout roughness on a non-critical admin subview that does not block urgent actions
- low-signal styling inconsistency with no broken flow

If there is any doubt whether an issue is security, auth, privacy, messaging, moderation, or operator-blocking, treat it as a blocker.

## 5. First-Hour Release Observability

Watch these signals during rollout and for at least the first hour after opening traffic. Treat sudden step-function changes as release regressions unless proven otherwise.

### Auth / Runtime Watchlist

- `POST /api/auth/login`: watch 5xx rate first. A new spike means auth or dependency regression, not normal user error.
- `POST /api/auth/refresh`: watch both 5xx and unusual 4xx growth. A sharp rise in 401/403 usually means cookie, proxy, host, or session rotation breakage.
- `POST /api/auth/password-reset/request`: watch 5xx rate. This should stay near zero.
- `POST /api/auth/verify-email/request` and `POST /api/auth/verify-email/complete`: watch for failure spikes after deploy, especially if email delivery still looks healthy.
- `POST /api/webauthn/auth/begin`, `POST /api/webauthn/auth/complete`, `POST /api/webauthn/register/begin`, and `POST /api/webauthn/register/complete`: watch begin and complete failures separately so challenge-storage/config regressions are distinguishable from browser/device issues.
- Compare 401/403/429 rates before and after release on newly hardened auth/session, WebAuthn, notifications, feedback attachment read, and profile/security mutation paths. Unexpected increases mean rollout friction even if 5xx stays quiet.
- Existing backend signal: rate-limit enforcement already logs `Rate limit exceeded` and Redis-required backend failures with `policy`, `path`, and `request_id`. Check `docker compose -f deploy/docker-compose.yml logs --tail=200 backend` before guessing.
- Existing browser signal: the web client already emits `Token refresh failed` in browser console when refresh/bootstrap breaks. Use that on the live hostname when server-side auth looks healthy but users loop back to signed-out state.

### Rate-Limit Watchlist

- Watch for 429 spikes on newly rate-limited endpoints immediately after deploy.
- First attention endpoints:
  `POST /api/webauthn/auth/begin`, `POST /api/webauthn/auth/complete`, `POST /api/webauthn/register/begin`, `POST /api/webauthn/register/complete`
  auth/session endpoints such as login, register, refresh, logout
  profile/security mutation endpoints such as verification, password reset, email change, and session revoke actions
  notifications routes if users report stale or broken notification access
  feedback attachment reads on `/api/feedback/attachments/*`
- Distinguish abuse from user harm:
  if 429s concentrate on a few IPs, identifiers, or obvious retry loops, the limits are likely blocking abuse
  if 429s rise alongside support complaints, successful-login drop, refresh 401/403 growth, or broken MFA completion, the limits are likely harming real users
- If 429s increase, inspect backend logs for the logged `policy` field and returned `X-RateLimit-Policy` header before changing anything.

### CSP / Browser Runtime Watchlist

- Open browser devtools on the live hostname and check for CSP violations on `/auth`, `/login`, `/register`, `/messages`, and `/search` first.
- In browser telemetry or Sentry, watch for blocked-script or CSP violation events, hydration failures, and bootstrap/init crashes.
- Confirm auth pages, messages, and search still bootstrap cleanly after deploy. These routes are the fastest signal that CSP hardening broke a real user flow.
- If users report blank screens, non-interactive auth forms, failed navigation, or infinite loading with quiet backend logs, treat that as probable CSP or hydration breakage and inspect browser console before blaming API health.
- Roll back the web image or config immediately if CSP violations or hydration/bootstrap failures block login, message access, verification, password reset, or search for multiple operators or real users.

### First-Hour Checks

1. Tail backend and web logs while running the manual auth, email, WebAuthn, notifications, messages, and search checks from Section 3.
2. Compare login, refresh, password-reset-request, email verification, and WebAuthn failures to the pre-release baseline if one exists. If not, use the first clean 10 minutes as the temporary baseline.
3. Check for unexpected 401/403/429 growth on hardened endpoints before widening traffic.
4. Check browser console on at least one auth route and one authenticated route for CSP, hydration, or bootstrap errors.
5. Keep rollout paused if operators cannot clearly tell whether the release is blocking abuse or blocking legitimate users.

## 6. Release / Rollback Checklist

### Pre-Release Checks

1. Confirm `GET /health`, `GET /ready`, and the expected security headers from Section 2.
2. Confirm production env alignment for `NEXT_PUBLIC_API_BASE_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `TRUST_PROXY_HEADERS`, `TRUSTED_PROXY_CIDRS`, and refresh-cookie settings.
3. Confirm one fresh login, one refresh, one email verification flow, and one password-reset request in the release candidate or local production-like smoke environment.
4. Confirm an operator is assigned to watch backend logs plus browser/runtime telemetry during the first hour.

### First-Hour Monitoring Checks

1. Watch login 5xx, refresh 5xx/4xx anomalies, password-reset-request 5xx, email verification failures, WebAuthn begin/complete failures, and 401/403/429 drift on hardened endpoints.
2. Watch 429 concentration on WebAuthn, auth/session, profile/security mutations, notifications, and feedback attachment reads.
3. Watch browser console and telemetry for CSP violations, blocked scripts, hydration failures, and auth/messages/search bootstrap errors.
4. Do not widen rollout while any of those signals are trending the wrong way without a known harmless explanation.

### Rollback Triggers

1. Login, refresh, verification, password reset, or WebAuthn failure rates spike enough to block normal user sign-in or recovery.
2. 429s clearly harm legitimate users on hardened endpoints instead of concentrating on abusive traffic.
3. CSP violations, blocked scripts, or hydration/bootstrap failures break auth, messages, search, or other core navigation.
4. Env or config mistakes create wrong API origin, cookie, proxy, host, or readiness behavior after deploy.

### Rollback Owner Actions

1. Announce rollback scope first: web only, app stack, or config-only.
2. Capture the failing signal before changing state: backend log tail, web log tail, and at least one browser-console error line for CSP/runtime issues.
3. Restore the last known-good web image/config first when the issue is CSP, bootstrap, or wrong `NEXT_PUBLIC_API_BASE_URL`.
4. Restore the last known-good backend/web release set when auth, session, or rate-limit behavior regressed and the fault is not isolated to web config.
5. Use `docs/rollback-recovery-runbook.md` for exact recovery sequencing.

### Verify After Rollback

1. Confirm `/ready` returns `200` and the web hostname loads without CSP or hydration errors.
2. Re-test login, refresh, logout, one verification or password-reset path, and one WebAuthn flow if staff MFA is in use.
3. Confirm 401/403/429 rates return to the pre-release pattern and backend logs stop showing new rollout-specific noise.
4. Confirm the rollback did not leave cookies, API base URL, or proxy settings in a half-fixed state.

## 7. Low-Risk Cleanup Included In This Pass

- Local Caddy manifest cache rule now matches `/manifest.webmanifest` instead of the stale `/manifest.json` path.
- Web CSP generation now normalizes the configured API origin and explicitly covers manifest, worker, frame, media, and image sources without widening scope.
- This document centralizes the canonical predeploy truth so operators do not have to infer it from older rollout or smoke notes.
