# Nexus

[![CI](https://github.com/rootlinux/nexus/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/rootlinux/nexus/actions/workflows/ci.yml)

<img src="nexus-banner.svg" alt="" width="100%" />

Invite-only social platform built with a security-first mindset. FastAPI backend, Next.js frontend, fully containerized deployment.

> A working application used as a deep-dive into authentication, session
> management, and platform hardening: passkeys and MFA on privileged sessions,
> refresh-token rotation, least-privilege service credentials, and
> configuration that refuses to start when it is unsafe.

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="screenshots/login.png" alt="Sign-in screen" /></td>
    <td width="50%"><img src="screenshots/register.png" alt="Invite-only registration screen" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Sign in</sub></td>
    <td align="center"><sub>Invite-only registration</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="screenshots/feed.png" alt="Home feed" /></td>
    <td width="50%"><img src="screenshots/profile.png" alt="User profile" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Feed</sub></td>
    <td align="center"><sub>Profile</sub></td>
  </tr>
</table>

Dark, editorial theme — [Fraunces](https://fonts.google.com/specimen/Fraunces) for display type paired with [Hanken Grotesk](https://fonts.google.com/specimen/Hanken+Grotesk) for UI/body text, self-hosted via `next/font`.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Next.js    │────▶│   FastAPI    │────▶│  PostgreSQL  │
│   (web/)     │     │  (backend/)  │     │              │
└─────────────┘     └──────┬───────┘     └──────────────┘
       ▲                   │
       │                   ▼
┌──────┴──────┐     ┌──────────────┐
│    Caddy    │     │    Redis     │
│ (reverse    │     │ (rate limit, │
│  proxy)     │     │  sessions)   │
└─────────────┘     └──────────────┘
```

- **`backend/`** — FastAPI app: routes, services, SQLAlchemy models, 43 Alembic migration files
- **`web/`** — Next.js frontend: dark design system, feed, discover, DMs
- **`nexus-mcp/`** — read-only [MCP](https://modelcontextprotocol.io) server for admin
  querying (see [its security model](nexus-mcp/README.md))
- **`deploy/`** — Docker Compose, Caddy configs, DB init scripts (see the
  [production migration & rollback runbook](deploy/RUNBOOK.md))
- **`.github/workflows/`** — CI with live PostgreSQL + Redis services

## Security Features

Found a vulnerability? See [SECURITY.md](SECURITY.md) for how to report it —
please don't open a public issue.

This is where most of the engineering effort went:

| Area | Implementation |
|------|----------------|
| **Authentication** | JWT access + refresh tokens, WebAuthn (passkeys), MFA enforcement on privileged sessions |
| **Session hardening** | Refresh token rotation, device fingerprinting, timezone-stable token timestamps |
| **Invite system** | Hashed invite codes, usage auditing, wave campaigns with concurrency-safe redemption |
| **Rate limiting** | Redis-backed, hardened against proxy/cache bypass |
| **Account security** | Email canonicalization, signup idempotency, password reset + email change token flows |
| **Authorization** | Staff permission system with audit logging, secure admin actions (MFA-gated) |
| **Moderation** | Signal intake, moderation queue, user blocks, media moderation |

**Production config validation:** `Settings()` fails fast on startup if it detects production-unsafe values — a weak `SECRET_KEY`, a `localhost`-origin CORS entry, a wildcard `ALLOWED_HOSTS`, or a Redis URL that isn't TLS + authenticated. If you deploy with `APP_ENV=production` and see:

> `Redis must use TLS in production. Set REDIS_URL to rediss://:password@host:port/db. If REDIS_URL points at a private Docker/VPC network with no TLS termination, set REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK=true to explicitly accept unencrypted Redis traffic within that network.`

Switch `REDIS_URL` to `rediss://:yourpassword@your-redis-host:6379/0` (TLS scheme + credentials). The only exception is Redis reachable exclusively over a private Docker/VPC network with no public exposure (e.g. the bundled `deploy/docker-compose.yml` stack, where `redis` has no published port) — there, set `REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK=true` to explicitly accept plaintext `redis://` within that network. Authentication (a password in the URL) is still required either way.

`REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK=true` does **not** accept just any host — it's not a blanket "trust me" switch. `REDIS_URL`'s host is still checked: an IP-literal host must be in a private or loopback range (RFC 1918, `127.0.0.0/8`, `::1`, etc.); a non-IP hostname (e.g. a Docker Compose service name like `redis`) must additionally be listed in `REDIS_PLAINTEXT_ALLOWED_HOSTS` (comma-separated), since a hostname can't be range-checked on its own. A public remote `redis://host` is rejected even with the flag set. `deploy/docker-compose.yml` sets `REDIS_PLAINTEXT_ALLOWED_HOSTS=redis` accordingly.

**Service credentials:** `/api/admin/service/*` (used by `nexus-mcp` and similar
integrations) authenticates with three independent, least-privilege credentials —
`SERVICE_TOKEN_READ`, `SERVICE_TOKEN_NOTIFY`, `SERVICE_TOKEN_DELETE`. There is no combined
"all scopes" token: presenting the read credential to a delete endpoint is rejected exactly
like an unknown token, and a scope whose credential is unset has no valid credential at all
rather than falling back to something broader. Issue `nexus-mcp` a `SERVICE_TOKEN_READ`
value only. The former all-powerful `ADMIN_SERVICE_TOKEN` (and its
`ENABLE_LEGACY_ADMIN_SERVICE_TOKEN` opt-in) has been **removed outright** — if either is
still present in a `.env` the backend reads, startup now aborts rather than silently
ignoring it. Covered by `test_service_auth_scopes` and `test_admin_service_scoped_auth`.

## Testing

**68 backend test modules**, weighted heavily toward security behaviour, plus frontend and
MCP suites. All four gates below run in CI on every pull request against a live PostgreSQL
and Redis. (`backend/tests/test_readme_claims.py` asserts the module count above still
matches the tree, so it cannot quietly go stale.)

| Suite | Command | What it covers |
|---|---|---|
| Backend | `cd backend && pytest` | 68 modules: auth, sessions, invites, moderation, media, migrations |
| Frontend | `cd web && npm test` | Service-worker fetch/notification behaviour |
| Frontend types | `cd web && npm run typecheck` | `tsc --noEmit` — an explicit gate, not just whatever `next build` happens to bundle |
| MCP | `cd nexus-mcp && npm test` | Read-only tool surface, config validation, HTTPS enforcement |

Security-relevant modules worth reading first:

- `test_privileged_session_mfa_enforcement` — MFA required for sensitive operations
- `test_first_admin_enrollment` — the one supported way to enrol a first admin passkey,
  and every misuse of it (wrong identifier, wrong password, non-staff account, an account
  that already has a key, the flag off, production)
- `test_rate_limit_hardening` / `test_proxy_and_cache_hardening` — bypass resistance
- `test_webauthn_auth_source_of_truth` — passkey auth integrity
- `test_service_auth_scopes` — least-privilege service credentials, fail-closed
- `test_wave_campaign_concurrency` — race-condition safety on invite redemption
- Migration tests for every security-relevant schema change

```bash
cd backend
./scripts/bootstrap_test_env.sh
pytest
# security-focused subset:
./scripts/run_targeted_security_tests.sh
```

Backend dependencies are split: `requirements.txt` is runtime-only and is all the
production image installs; `requirements-dev.txt` adds pytest, httpx, and a pinned ruff for
CI and local development.

## Running Locally

```bash
# 1. Configure
cp backend/.env.example backend/.env
cp deploy/.env.local-smoke.example deploy/.env.docker

# 2. Start everything (Postgres, Redis, backend, frontend, Caddy)
./deploy/scripts/docker-start.sh

# 3. Optional: permanently delete the local DB volume + restart from scratch
CONFIRM_RESET_LOCAL_DB=yes ./deploy/scripts/docker-reset-and-start.sh
```

On macOS you can start the same flow from Finder by double-clicking
`START-DOCKER.command` in the project root. It opens Docker Desktop if it is not already
running, waits for every service to report healthy, and then opens
`http://app.nexus.localtest.me`. `STOP-DOCKER.command` stops only the Nexus containers — it
does not delete the PostgreSQL/Redis/Caddy volumes, `backend/uploads`, or
`backend/feedback_private_uploads`.

> **Upgrading a stack created before the Nexus rename?** Its data lives in a PostgreSQL
> database literally named `xplatform`, and the Compose default is now `nexus`.
> `POSTGRES_DB` only creates a database on a *fresh* data directory — it never renames an
> existing one — so read
> [Renaming a pre-Nexus database](deploy/RUNBOOK.md#renaming-a-pre-nexus-database) before
> you restart. Either keep the old name with `POSTGRES_DB=xplatform`, or run
> `deploy/scripts/rename-legacy-database.sh` once. A brand-new install needs neither.

The local scripts layer [`deploy/docker-compose.local.yml`](deploy/docker-compose.local.yml)
over the production-oriented base Compose file. This selects the HTTP-only
`localtest.me` Caddy configuration and pins browser-facing origins to the local
Nexus hostnames. Production deployments must use the base Compose file by itself
with [`deploy/Caddyfile.prod`](deploy/Caddyfile.prod) and explicit real hostnames.

`.env.example` files exist for [`backend/`](backend/.env.example),
[`web/`](web/.env.example), [`nexus-mcp/`](nexus-mcp/.env.example), and the
[Docker smoke stack](deploy/.env.local-smoke.example). **Every value in
these files is a placeholder** — generate your own secrets and never deploy
with an example value still in place (production startup rejects known
placeholder `SECRET_KEY` values, but treat that as a backstop, not a plan).

## First Run: Invites and the First Administrator

Nexus is invite-only. `/register` requires a valid invite code and a freshly migrated
database has none, so a brand-new install cannot sign anybody up until you create one.
Both escape hatches below are **off by default and rejected outright in production** —
`Settings()` refuses to start if either is enabled with a production `APP_ENV`.

### Option A — mint an invite code (no config change, no restart)

```bash
docker exec nexus-backend python -m app.scripts.create_invite
# INVITE_CODE=<paste this on /register>
```

`--created-by <username>`, `--max-uses`, `--expires-days`, and `--note` are available. On a
fresh database the invite is created unattributed (`created_by_id IS NULL`, allowed since
migration `037_invite_created_by_nullable`) rather than fabricating a placeholder user
account to own it. In production `--created-by` is required, so real invites always trace
back to an accountable staff member.

The code is printed once and stored only as a hash — a lost code cannot be recovered, mint
a new one.

### Option B — create the first administrator

An administrator needs a passkey: privileged accounts cannot sign in with a password
alone. The ordinary passkey-registration endpoint needs a session, and a staff account
cannot get a session without a passkey — so the first credential comes through a dedicated,
self-closing enrolment path. Three steps, no database editing and no log-scraping:

1. **Create the identity.** In `deploy/.env.docker` set `APP_ENV=development`,
   `ENABLE_BOOTSTRAP_ADMIN=true`, and fill in `BOOTSTRAP_ADMIN_USERNAME` /
   `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` (16+ characters; a zxcvbn score of
   at least 3 is enforced at startup) / `BOOTSTRAP_ADMIN_DISPLAY_NAME`. Restart with
   `./deploy/scripts/docker-start.sh`.

2. **Enrol its first passkey.** Set `ENABLE_ADMIN_WEBAUTHN_RECOVERY=true` and
   `ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER=<the same BOOTSTRAP_ADMIN_USERNAME>`, restart, then
   open **`/auth/admin-enrollment`** and register a passkey with the username and password
   from step 1. (Attempting a normal sign-in first also links you there.)

   The endpoint answers `404` unless the flag is on, and `403` unless the identifier
   matches that one configured account, the account is staff, and it owns no credential
   yet — so it closes itself the moment the passkey is registered.

3. **Turn both flags back off** and restart. Sign in normally: password, then passkey.
   Privileged access still requires the full MFA check on every privileged session.

Implementation: `app/bootstrap.py`, `app/api/routes/auth.py`
(`/admin-recovery/webauthn-token`), `app/api/routes/webauthn.py`
(`/recovery/register/*`), and the enrolment page at
`web/src/app/auth/admin-enrollment/page.tsx`. The happy path and each misuse case are
pinned by `backend/tests/test_first_admin_enrollment.py`.

## Email Delivery

Nexus sends transactional email for signup verification, password reset, and email-change confirmation. The provider is controlled by `MAIL_PROVIDER` and defaults to `capture`:

- **`capture` (default, used for local/dev)** — no real email is sent and no external service is required. Each outgoing message is written as a JSON file (subject, body, and the verification/reset link) to `MAIL_CAPTURE_DIR` (default `tmp/mail`). In the Docker smoke stack that directory isn't writable by the app user, so it automatically falls back to `/tmp/nexus-mail-capture/tmp/mail` inside the container (a warning is logged when this happens). Read the latest captured email to get a working verification link during local testing:
  ```bash
  docker exec nexus-backend sh -c '
    dir=tmp/mail; [ -d /tmp/nexus-mail-capture/tmp/mail ] && dir=/tmp/nexus-mail-capture/tmp/mail
    ls -t "$dir" | head -1 | xargs -I{} cat "$dir/{}"
  '
  ```
- **`resend`** — sends real email through [Resend](https://resend.com). Requires `RESEND_API_KEY`, plus a real `MAIL_FROM_EMAIL`/`MAIL_FROM_NAME` and a production `WEB_BASE_URL` (a `.local`/`.localtest.me` base URL is rejected when a real provider is configured).

Keep `MAIL_PROVIDER=capture` for any local or smoke-test stack — registration, password reset, and email-change all work end-to-end without a real mail service. Only switch to `resend` (and supply `RESEND_API_KEY`) for the actual deployed environment.

## Stack

**Backend:** Python · FastAPI · SQLAlchemy + Alembic · PostgreSQL · Redis · pytest
**Frontend:** TypeScript · Next.js · Tailwind
**Infra:** Docker Compose · Caddy · GitHub Actions

## Status

Active development, **not a production service**. This is an invite-only beta
architecture running as a personal project: waitlist, invite campaigns, passkey auth,
staff permissions, and moderation tooling are implemented and tested; the feature surface
is still expanding.

Known limitations, stated plainly:

- **No load or scale testing.** Feed ranking and discovery are correct, not benchmarked.
- **Lifetime media quotas are tracked but not enforced** — only the daily per-user upload
  cap is. See `reserve_upload_quota`'s docstring for why.
- **The Caddy per-route upload size limits are duplicated by hand** from
  `app/core/config.py`. Changing a Python limit means editing `deploy/Caddyfile*` too;
  there is no automatic sync.
- **No external security audit.** Every security claim above points at code and a test in
  this repository — that is evidence, not third-party assurance.
