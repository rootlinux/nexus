# Contributing

Nexus is a portfolio project, but issues and pull requests are welcome —
bug reports, small fixes, and focused improvements are the most useful kind.

## Before you start

For anything larger than a small fix (new features, schema changes,
refactors touching auth/session/admin code), open an issue first to discuss
the approach. It saves rework on both sides.

Found a security vulnerability instead? Do not open a public issue — see
[SECURITY.md](SECURITY.md).

## Local setup

See [Running Locally](README.md#running-locally) in the README. Short version:

```bash
cp backend/.env.example backend/.env
cp deploy/.env.local-smoke.example deploy/.env.docker
./deploy/scripts/docker-start.sh
```

## Project layout

- `backend/` — FastAPI + SQLAlchemy/Alembic + PostgreSQL + Redis
- `web/` — Next.js frontend
- `nexus-mcp/` — read-only MCP server for admin querying (Model Context Protocol)
- `deploy/` — Docker Compose, Caddy, environment templates

## Making changes

- Keep PRs focused — one logical change per PR.
- Add or update tests for behavior you change. This project is weighted
  heavily toward security-behavior tests (rate limiting, proxy trust, auth,
  session handling) — changes in those areas need test coverage.
- Follow the existing code style in the file/module you're touching rather
  than introducing a new convention.
- Don't commit `.env` files, credentials, or personal data. `.env.example`
  files should only ever contain placeholder values.

## Running tests

```bash
# Backend
cd backend
./scripts/bootstrap_test_env.sh            # installs requirements-dev.txt into .venv
pytest
./scripts/run_targeted_security_tests.sh   # security-focused subset

# nexus-mcp
cd nexus-mcp
npm ci
npm run typecheck
npm test

# web
cd web
npm ci
npm test
npm run typecheck
npm run lint
npm run build
```

Backend dependencies are split in two: `requirements.txt` is runtime-only (it is exactly
what the production image installs) and `requirements-dev.txt` layers pytest, httpx, and a
pinned ruff on top. Add a new test-only dependency to the dev file, never the runtime one.

CI runs all of the above on every pull request; a red check blocks merge.

## Commit messages

Conventional-commit style is used throughout the history:

```
<type>: <short description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`,
`security`.

## Pull requests

- Describe what changed and why, not just what.
- Call out any migration files, env var changes, or deployment steps a
  reviewer needs to know about.
- Note any known limitations or follow-up work rather than leaving it
  implicit.
