# Nexus Monorepo

This repository contains the Nexus platform codebase and operational docs for local development.

## Repository structure

- `backend/`: FastAPI backend and tests
- `web/`: Next.js web application
- `brand/`: source brand assets and exported runtime assets
- `deploy/`: local stack and deployment helpers
- `docs/`: rollout, security, smoke, and runbook documentation

> **Not:** `mobile/` dizini şu an kapsam dışıdır ve repo'ya dahil edilmemiştir.

## Local development

### Backend

Use the backend virtual environment documented in [backend/README.md](backend/README.md).

```bash
backend/scripts/bootstrap_test_env.sh
backend/scripts/run_targeted_security_tests.sh all
```

### Web

```bash
cd web
npm install
npm run dev
```

## GitHub preparation notes

- Local caches, virtual environments, uploads, logs, and verification artifacts are ignored.
- Environment files are ignored; example env files can still be committed.
- `mobile/` dizini `.gitignore`'da; ayrı bir repo olarak yönetilecek.

## Before publishing

Review the following locally before the first push:

- any real secrets in untracked environment files
- whether large local archives such as `stitch.zip` should remain outside version control

## Secret isolation

- Use a different `SECRET_KEY` for every environment.
- The Docker/local-smoke `deploy/.env.docker` secret must not match backend local, development, staging, or production secrets.
- Local, smoke, staging, and production secrets must never be reused or copied across environments.

## Deploy config separation

- `deploy/Caddyfile` is local smoke only and intentionally includes local-only behavior such as `auto_https off`.
- `deploy/Caddyfile.prod` is the production-only reverse-proxy config and must be used for real deployments.
- `deploy/.env.docker` and `deploy/.env.local-smoke.example` are for the local Docker smoke stack only, not production.
- `backend/.env.example` is for direct backend local development only, not Docker smoke or production.

## Pre-production release gate

- Database migrations applied to the target environment.
- Auth runtime smoke check passed against the deployed stack.
- CSP runtime verification passed in the deployed browser flow.
- Production `SECRET_KEY` is unique to production, rotated as needed, and not shared with smoke/local/staging.
- Correct reverse-proxy file selected: `deploy/Caddyfile.prod` for production, never `deploy/Caddyfile`.
- Rate limiting is enabled or Redis-backed rate limiting is available for runtime paths that require it.
- Environment variables reviewed for production values, hosts, proxy CIDRs, mail settings, and secret isolation.
