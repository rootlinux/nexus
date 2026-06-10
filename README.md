# Nexus

Invite-only social platform built with a security-first mindset. FastAPI backend, Next.js frontend, fully containerized deployment.

> Built as a deep-dive into authentication, session management, and platform hardening — the defensive side of the skills I'm building toward offensive security work.

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

- **`backend/`** — FastAPI app: routes, services, SQLAlchemy models, 36 Alembic migrations
- **`web/`** — Next.js frontend: dark design system, feed, discover, DMs
- **`deploy/`** — Docker Compose, Caddy configs, DB init scripts
- **`.github/workflows/`** — CI with live PostgreSQL + Redis services

## Security Features

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

## Testing

40+ test modules, heavily weighted toward security behavior:

- `test_privileged_session_mfa_enforcement` — MFA required for sensitive operations
- `test_rate_limit_hardening` / `test_proxy_and_cache_hardening` — bypass resistance
- `test_webauthn_auth_source_of_truth` — passkey auth integrity
- `test_phase3_wave_campaign_concurrency` — race-condition safety on invite redemption
- Migration tests for every security-relevant schema change

```bash
cd backend
./scripts/bootstrap_test_env.sh
pytest
# security-focused subset:
./scripts/run_targeted_security_tests.sh
```

## Running Locally

```bash
# 1. Configure
cp backend/.env.example backend/.env
cp deploy/.env.local-smoke.example deploy/.env

# 2. Start everything (Postgres, Redis, backend, frontend, Caddy)
./deploy/scripts/docker-start.sh

# 3. Reset DB + restart from scratch
./deploy/scripts/docker-reset-and-start.sh
```

## Stack

**Backend:** Python · FastAPI · SQLAlchemy + Alembic · PostgreSQL · Redis · pytest
**Frontend:** TypeScript · Next.js · Tailwind
**Infra:** Docker Compose · Caddy · GitHub Actions

## Status

Active development. Invite-only beta architecture — waitlist, invite campaigns, and moderation tooling are functional; feature surface still expanding.
