# Rollback / Recovery Mini Runbook

Use this runbook for the current Docker Compose deployment in [`deploy/docker-compose.yml`](/Users/berkesahin/Desktop/X/deploy/docker-compose.yml). It assumes operators run commands from the repo root.

## Current stack

- Deploy path: `docker compose -f deploy/docker-compose.yml ...`
- Local production-like smoke hostnames: `app.x.localtest.me:3000` for web and `api.x.localtest.me:8000` for backend
- Services: `postgres`, `redis`, `backend`, `web`
- Backend boot path: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Liveness: `GET /health`
- Readiness: `GET /ready`
- Compose healthchecks exist for `postgres`, `redis`, and `backend`; `web` needs manual reachability checks
- Web runtime dependency: `NEXT_PUBLIC_API_BASE_URL`
- Web session model: access token in browser session storage, refresh token in HttpOnly cookie on `/api/auth`

Treat the `localtest.me` hostnames in this document as local smoke defaults only. They are not production source-of-truth values.

## First 15 minutes after release

1. Check container state.
   `docker compose -f deploy/docker-compose.yml ps`
2. Check backend logs first.
   `docker compose -f deploy/docker-compose.yml logs --tail=100 backend`
3. Confirm DB migration state.
   `docker compose -f deploy/docker-compose.yml exec postgres psql -U postgres -d xplatform -c "select version_num from alembic_version;"`
4. Check liveness.
   `curl -fsS http://<api-host>/health`
5. Check readiness.
   `curl -i http://<api-host>/ready`
6. Check frontend reachability.
   `curl -I http://<web-host>/`
7. Do auth smoke from the real web hostname.
   Login, refresh once, logout, then login again.
8. Do admin smoke with an existing admin account.
   Open `/admin` and confirm the page loads data without immediate 401/403/5xx noise.
9. Do one core product smoke.
   Load feed, open one post, create one low-risk test post or reply if release policy allows it.
10. Check log sanity.
   `docker compose -f deploy/docker-compose.yml logs --tail=200 web backend redis postgres`

Treat `/health=200` plus `/ready=503` as a dependency problem, not a successful release.

## Release Gate Observability Shortlist

- Auth/runtime:
  watch login 5xx, refresh 5xx and unusual refresh 4xx growth, password-reset-request 5xx, email verification failures, WebAuthn begin/complete failures, and unexpected 401/403/429 shifts on hardened endpoints.
- Rate-limit:
  watch for 429 spikes first on WebAuthn routes, auth/session routes, profile/security mutations, notifications, and feedback attachment reads.
- CSP/runtime:
  inspect live-browser console plus browser telemetry for CSP violations, blocked scripts, hydration failures, and `/auth`, `/messages`, or `/search` bootstrap breakage.
- Existing log sources:
  backend rate-limit events already log `Rate limit exceeded` plus `policy`, `path`, and `request_id`
  browser refresh/bootstrap issues already surface as `Token refresh failed` in web console
- If the signal points to CSP, wrong API base URL, cookies, proxy trust, or host allowlist mismatch, treat config rollback as the first recovery path instead of assuming an application bug.

## Rollback Owner Checklist

1. Name the rollback owner and whether the change is `web only`, `config only`, or `full app release`.
2. Capture evidence before rollback:
   `docker compose -f deploy/docker-compose.yml logs --tail=200 backend web`
   browser console errors for live `/auth` or the affected route
3. If the break is CSP/runtime or wrong web API origin, restore the last known-good web image/config first.
4. If the break is auth/session/rate-limit behavior across backend routes, restore the last known-good backend and web release pair.
5. After rollback, verify `/ready`, login, refresh, one verification/reset path, and one affected user flow before reopening traffic.

## Local production-like smoke

- Use `deploy/.env.local-smoke.example` as the template for Compose smoke runs.
- The canonical local smoke host model is:
  `http://app.x.localtest.me:3000` for the web app and `http://api.x.localtest.me:8000` for the API.
- `localtest.me` resolves to loopback, so this keeps the deploy path on non-`localhost` hostnames without editing `/etc/hosts`.
- Keep `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `NEXT_PUBLIC_API_BASE_URL` aligned to those exact values unless you intentionally choose a different non-localhost domain scheme.
- Before backend-only test runs outside Compose, use the canonical backend environment at `backend/.venv`.

## Pre-Launch Admin Session Hygiene

Before opening real traffic on the final deployment, revoke any active refresh tokens that still belong to staff accounts carried over from pre-launch testing.

- Safe one-time command on the Compose-backed deployment:
  `docker compose -f deploy/docker-compose.yml exec postgres psql -U postgres -d xplatform -c "UPDATE refresh_tokens AS rt SET revoked = TRUE FROM staff_permissions AS sp WHERE sp.user_id = rt.user_id AND rt.revoked = FALSE;"`
- Verify how many staff sessions remain active:
  `docker compose -f deploy/docker-compose.yml exec postgres psql -U postgres -d xplatform -c "SELECT COUNT(*) AS active_staff_refresh_tokens FROM refresh_tokens AS rt JOIN staff_permissions AS sp ON sp.user_id = rt.user_id WHERE rt.revoked = FALSE;"`
- Scope note:
  this is appropriate as a final pre-launch hygiene step because it clears privileged pre-launch browser sessions without touching account rows or non-staff user data.
- Do not run it during ordinary local smoke unless you intentionally want to invalidate local admin sessions.

## Staging Admin WebAuthn Recovery

Use this only in a controlled staging or other live-like environment when the retained admin account exists, has no registered security key, and normal admin login is blocked.

- Fail-closed config:
  set `ENABLE_ADMIN_WEBAUTHN_RECOVERY=true` only in staging/test-like environments and set `ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER` to the exact retained admin username or email.
- Recovery scope:
  this path does not mint a full admin session. It only issues a short-lived recovery token that can register a WebAuthn credential for the configured retained admin account.
- Operator flow:
  1. If needed, complete the normal password-reset email flow for the retained admin first so the operator knows the current password.
  2. Call `POST /api/auth/admin-recovery/webauthn-token` with the configured retained admin identifier and current password.
  3. Call `POST /api/webauthn/recovery/register/begin` with the returned `recovery_token`.
  4. Complete browser security-key registration with `POST /api/webauthn/recovery/register/complete`.
  5. Disable `ENABLE_ADMIN_WEBAUTHN_RECOVERY` again after the key is enrolled.
- Safety notes:
  non-staff users cannot use this path, staff accounts that already have a key are rejected, and production remains blocked by config validation.

## Deploy Fail / Startup Fail

### Container fails to build

- Likely causes:
  bad image build context, missing build arg like `NEXT_PUBLIC_API_BASE_URL`, broken dependency install, syntax error in app code.
- First checks:
  `docker compose -f deploy/docker-compose.yml build backend web`
  `docker compose -f deploy/docker-compose.yml config`
- Recovery:
  fix the missing env/build arg or build error, then rebuild only the failed service.
- Rollback:
  if the new image never built, keep the currently running stack in place. There is nothing to roll back in the database yet.

### Backend container exits on boot

- Likely causes:
  `alembic upgrade head` failed, required env missing, production config validation failed, DB unavailable.
- First checks:
  `docker compose -f deploy/docker-compose.yml logs --tail=200 backend`
  `docker compose -f deploy/docker-compose.yml ps`
- Recovery:
  if the error is env/config, correct env and restart `backend`.
  if the error is migration-related, follow the migration section below before restarting traffic.
- Rollback:
  do not keep restarting a crash-looping backend into live traffic. Stop the rollout, restore the last known-good backend/web image or config set, then verify `/ready`.

### Frontend starts but cannot reach API

- Likely causes:
  wrong `NEXT_PUBLIC_API_BASE_URL`, API host not reachable from browser, CORS mismatch, proxy/host mismatch.
- First checks:
  `docker compose -f deploy/docker-compose.yml logs --tail=100 web backend`
  inspect the deployed `NEXT_PUBLIC_API_BASE_URL` value
  `curl -i http://<api-host>/health`
  `curl -i http://<api-host>/ready`
- Recovery:
  correct `NEXT_PUBLIC_API_BASE_URL` and redeploy `web`.
  if browser requests fail with CORS, correct `CORS_ALLOWED_ORIGINS` on `backend` and restart `backend`.
- Rollback:
  if only web is wrong, roll back only the `web` image/config. Do not touch the DB.

### Compose stack is up but health/readiness is failing

- Likely causes:
  `postgres` or `redis` unhealthy, backend can answer `/health` but not `/ready`, host header mismatch on readiness checks.
- First checks:
  `docker compose -f deploy/docker-compose.yml ps`
  `docker compose -f deploy/docker-compose.yml logs --tail=100 postgres redis backend`
  `curl -i http://<api-host>/ready`
- Recovery:
  recover the failing dependency first. `/ready` requires both DB and Redis.
- Rollback:
  if the new app version is the only change and dependencies are healthy, restore the last known-good app version. If dependencies are broken, rolling back app images will not fix readiness.

## Migration Fail

- Current deploy behavior:
  backend startup runs `alembic upgrade head` before `uvicorn`. A migration failure can keep `backend` fully down.
- Verify current DB revision:
  `docker compose -f deploy/docker-compose.yml exec postgres psql -U postgres -d xplatform -c "select version_num from alembic_version;"`
  If the backend container is healthy enough for exec, this is also valid:
  `docker compose -f deploy/docker-compose.yml exec backend alembic current`
- Verify current repo migration head before release decisions:
  `cd backend && .venv/bin/alembic heads`
- Stop a bad rollout safely:
  stop sending traffic to the new backend/web first.
  stop or scale down the failing app containers so they do not keep retrying while you inspect the DB state.
- Roll back app or roll forward migration:
  roll back app only if the DB revision is still on the prior known-good revision and the failed release did not advance schema state.
  prefer roll forward if `alembic_version` already advanced or the migration partially changed schema.
  do not assume `alembic downgrade` is safe. This repo does not provide a verified automated schema rollback path in the deploy workflow.
- Before resuming traffic:
  confirm the intended revision in `alembic_version`
  confirm backend starts cleanly
  confirm `GET /ready` returns `200`
  confirm one auth flow and one product flow work against the migrated schema

## Redis / Postgres Unavailable

### Redis unavailable

- Confirm:
  `docker compose -f deploy/docker-compose.yml logs --tail=100 redis backend`
  `curl -i http://<api-host>/ready`
- Expected behavior:
  `/ready` returns `503`
  production-only Redis-required rate limits can hard-fail with `503`
  affected areas include login, register, invite validation/redeem, posting, and DM send
  refresh may still work because its rate limit does not require Redis-only mode
- Operator action:
  restore Redis first, then retest `/ready`, login, and one write path.
- Degraded vs blocked:
  degraded: some routes may still answer
  hard-blocked: readiness, Redis-required protected flows in production

### Postgres unavailable

- Confirm:
  `docker compose -f deploy/docker-compose.yml logs --tail=100 postgres backend`
  `curl -i http://<api-host>/ready`
- Expected behavior:
  `/ready` returns `503`
  backend startup or authenticated/API traffic will fail because the app depends on DB connectivity
- Operator action:
  restore Postgres first, then re-check migration state and `/ready`.
- Degraded vs blocked:
  blocked: startup, auth, feed, admin, invites, notifications, DM, writes

## Auth / Cookie / Base-URL / Proxy Misconfig

### Login works locally but fails behind proxy

- Symptoms:
  browser login or refresh fails only behind the public hostname, cookies missing, redirects or mixed-scheme behavior looks wrong.
- Inspect:
  `TRUST_PROXY_HEADERS`
  `TRUSTED_PROXY_CIDRS`
  `ALLOWED_HOSTS`
- Verify fix:
  ensure the proxy source IPs are inside `TRUSTED_PROXY_CIDRS`
  ensure the public API hostname is in `ALLOWED_HOSTS`
  retry login through the real HTTPS hostname

### Cookies not sticking after HTTPS cutover

- Symptoms:
  login returns success but refresh/logout/authenticated page loads behave like the user is logged out.
- Inspect:
  `REFRESH_COOKIE_SECURE`
  `REFRESH_COOKIE_DOMAIN`
  `REFRESH_COOKIE_SAMESITE`
  browser response headers on `/api/auth/login` and `/api/auth/refresh`
- Verify fix:
  confirm `Set-Cookie` is present for `x_refresh_token`
  confirm cookie path is `/api/auth`
  confirm secure/domain values match the public deployment shape
  confirm refresh succeeds from the web app

### Frontend points at the wrong API

- Symptoms:
  HTML loads but browser API calls hit the wrong host, wrong port, or an origin that browsers cannot reach.
- Inspect:
  `NEXT_PUBLIC_API_BASE_URL` in the `web` deployment
- Verify fix:
  `curl -I http://<web-host>/`
  load the site and confirm browser requests target the intended API hostname

### Wrong host or proxy allowlist

- Symptoms:
  `400`/host rejection, readiness healthcheck fails unexpectedly, app behaves differently direct-to-origin versus through proxy.
- Inspect:
  `ALLOWED_HOSTS`
  `TRUST_PROXY_HEADERS`
  `TRUSTED_PROXY_CIDRS`
- Verify fix:
  direct origin check: `curl -H 'Host: <allowed-api-host>' http://127.0.0.1:8000/ready`
  proxied host check through the public hostname: `curl -i https://<api-host>/ready`

### Wrong browser origin allowlist

- Symptoms:
  web can load but authenticated browser requests fail on CORS preflight or credentialed API calls.
- Inspect:
  `CORS_ALLOWED_ORIGINS`
- Verify fix:
  ensure the exact public web origin is listed with scheme and host, then retry login and one authenticated API request from the browser.

## Known High-Risk Config Values

- `SECRET_KEY`: must be strong and stable for the deployment.
- `APP_ENV`: production safety checks change behavior.
- `DATABASE_URL`: backend and Alembic both depend on it.
- `REDIS_URL`: readiness and Redis-backed rate limits depend on it.
- `ALLOWED_HOSTS`: wrong values can block public traffic and readiness checks.
- `CORS_ALLOWED_ORIGINS`: must exactly match the public web origin for credentialed browser API use.
- `NEXT_PUBLIC_API_BASE_URL`: wrong value breaks web-to-API traffic even when containers are healthy.
- `TRUST_PROXY_HEADERS`: must only be enabled when the backend is actually behind a trusted proxy.
- `TRUSTED_PROXY_CIDRS`: required when proxy trust is enabled; wrong values break scheme/host/IP handling.
- `REFRESH_COOKIE_SECURE`: must stay true for real HTTPS production.
- `REFRESH_COOKIE_DOMAIN`: set only when cross-subdomain cookie scope is actually required.
- `REFRESH_COOKIE_SAMESITE`: wrong value can break cross-site auth behavior.

## Operator Notes

- `/health` only proves the app process is alive. Use `/ready` for release decisions.
- The backend healthcheck in Compose calls `/ready`, not `/health`.
- The web app uses cookie-backed refresh on `/api/auth/*`; auth problems after proxy changes are usually config problems, not frontend code problems.
- Be honest about schema rollback risk. If DB state advanced, forward repair is usually safer than forced downgrade.
