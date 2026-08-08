# Production Migration & Rollback Runbook

Operational procedure for deploying database migrations to Nexus's production
environment, and for rolling the deployment back if something goes wrong.
This document describes *what* must happen and in *what order* — it
intentionally does not embed environment-specific hostnames, credentials, or
paths. Substitute your actual deployment's values when executing each step.

Scope: the `deploy/` Docker Compose stack (`postgres`, `redis`, `backend`,
`web`, `caddy` services) described in the [README](../README.md#architecture),
and the Alembic migration chain under `backend/alembic/versions/`.

## 1. Pre-deployment backup

Before running any migration against the production database:

1. **Record the currently deployed state** — the running application commit
   SHA and the current Alembic revision (`alembic current`, run against the
   production database, read-only). Store both alongside the backup so a
   restore can be matched to the exact code+schema pair it came from.
2. **Take a full database backup** (e.g. `pg_dump`/`pg_dumpall` against the
   `postgres` service, or your managed database provider's native backup/snapshot
   feature). Use the custom/directory dump format so it can be restored with
   `pg_restore` independently of the original server's exact configuration.
3. **Verify the backup is readable and restorable** before proceeding —
   restore it into a separate, disposable database instance (never the
   production instance) and confirm:
   - the restore command completes without error
   - `alembic current` against the restored copy reports the same revision
     recorded in step 1
   - row counts for a small set of core tables (e.g. users, posts) are
     non-zero and plausible
   Discard the disposable verification instance afterward.
4. **Back up the file-backed upload storage** — copy `backend/uploads/` and
   `backend/feedback_private_uploads/` (the directories configured via
   `LOCAL_UPLOAD_DIR` and `FEEDBACK_ATTACHMENT_LOCAL_DIR`) to backup storage
   separate from the production host, preserving file contents and directory
   structure exactly. These directories are not managed by Alembic and are
   not restored by a database restore — they require their own backup and
   restore path.
5. **Preserve the production environment configuration securely** — record
   which environment variables are set for the deployment (names and, where
   necessary for audit purposes, non-secret values only) using your
   organization's secret manager or encrypted secret storage. Never commit
   `.env` files, secret values, tokens, or keys to source control or to this
   repository, and never include them in backup archives stored alongside
   plain database dumps.

Do not proceed past this section until backup, restore-verification, and
upload-directory backup have all completed successfully.

## 2. Migration order

Apply the three migrations introduced in this round strictly in order —
each has a linear `down_revision` dependency on the previous one:

```
039_media_assets_and_feedback_reports
      │
      ▼
040_refresh_token_families
      │
      ▼
041_feedback_read_capability
```

Run `alembic upgrade head` (or step through individually with
`alembic upgrade <revision>` if you want a checkpoint between each). Do not
skip ahead or apply `041` before confirming `039` and `040` succeeded.

### Required review before `041`

Migration `041_feedback_read_capability` narrows feedback-attachment read
access (`can_view_feedback`) — moderators no longer receive it implicitly the
way an earlier admin-session check previously implied. **Before applying
`041`, review current moderator role assignments** and grant
`can_view_feedback` explicitly to any moderator who still needs it. Applying
`041` without this review will silently remove feedback-attachment access
from moderators who previously had it.

## 3. Required and conditional configuration

- **`API_PUBLIC_BASE_URL` must be set to a valid HTTPS URL** in production.
  This is enforced at application boot — the app will refuse to start with a
  missing value, a non-HTTPS scheme, a loopback/local hostname, or a URL
  containing a path or query string. Attachment and media URLs are always
  built from this configured value, never from the incoming request's `Host`
  header.
- **`APP_HOST` and `API_HOST` are required, not defaulted.** They are the public
  hostnames Caddy terminates TLS for. They previously defaulted to `app.example.com` /
  `api.example.com`, which meant an unconfigured stack asked Let's Encrypt for a
  certificate for a domain it does not own; Compose now refuses to start without them.
- **`FEEDBACK_REPORT_TO_EMAIL` is required whenever a real mail provider is
  configured.** In-app problem reports (and the signed attachment links inside them) are
  delivered there. It used to default to a placeholder `example.com` address, so an
  unconfigured deployment mailed real user reports into a void with no error. Startup now
  rejects an empty value and any reserved `example.*` domain.
- **`ADMIN_SERVICE_TOKEN` / `ENABLE_LEGACY_ADMIN_SERVICE_TOKEN` no longer
  exist.** `/api/admin/service/*` is authenticated only by the independent
  `SERVICE_TOKEN_READ` / `SERVICE_TOKEN_NOTIFY` / `SERVICE_TOKEN_DELETE`
  credentials. Issue each consumer only the scope it needs, and **unset both
  removed variables everywhere** — including any `.env` file the backend
  reads, where a leftover key now aborts startup with
  `Extra inputs are not permitted`. Leftover *process* environment variables
  (e.g. from a Compose file) are ignored rather than fatal, so grep your
  deployment config as well as your `.env`.
- **`SIGNING_KEY_LEGACY_VERIFY_UNTIL` is optional and must be time-bounded.**
  Only set it if this deployment needs to continue honoring signed artifacts
  (e.g. outstanding feedback-attachment links) issued before the signing-key
  purpose separation took effect. If set, use a real, specific future UTC
  timestamp — never a placeholder or an open-ended value — so legacy
  verification support automatically expires.

### Renaming a pre-Nexus database

Stacks first deployed before the project was renamed to Nexus hold their data
in a PostgreSQL database named `xplatform`. The Compose default is now
`nexus`. **`POSTGRES_DB` only creates a database on a fresh data directory —
it never renames an existing one**, so an upgraded stack pointed at the new
name would connect to a database that does not exist and the old data would
appear to have vanished. Pick one, once:

- **Keep the old name (no downtime, nothing to run):** set
  `POSTGRES_DB=xplatform` in your deployment env file. Fully supported; the
  name is just a string.
- **Rename in place:** stop the app, run the rename, restart.

  ```bash
  docker compose -f deploy/docker-compose.yml stop backend web
  ./deploy/scripts/rename-legacy-database.sh
  docker compose -f deploy/docker-compose.yml up -d
  ```

  The script refuses to act if the target name already exists or if any
  connection to the legacy database is still open, and it renames rather than
  copies — no data is dropped or rewritten. Take the section 1 backup first
  regardless.

## 4. Deploy

Build and roll out the new application images (`backend`, `web`) after the
migration step above has completed successfully. The `backend` service's
container entrypoint runs `alembic upgrade head` before starting the API
process — confirm this happened by checking the deployed revision again
after rollout (`alembic current` should now report `041_feedback_read_capability`).

## 5. Post-deployment health and smoke checks

Before considering the deployment complete:

- `backend`'s health endpoint (`/ready`) returns healthy.
- `alembic current` on the production database reports
  `041_feedback_read_capability`.
- A basic authenticated request path succeeds end-to-end (e.g. log in, load
  the feed).
- Submitting a feedback report with an attachment succeeds and the generated
  attachment URL begins with the configured `API_PUBLIC_BASE_URL`, not a
  request-derived host.
- Uploading a profile image or post image succeeds and respects the
  configured per-user media quota.
- No unexpected spike in 5xx responses or error-rate alerts in the minutes
  following rollout.

## 6. Media cleanup stays dry-run only

`backend/app/scripts/media_cleanup_dry_run.py` only reports orphaned media
candidates — it never deletes files. Do not wire any physical deletion step
into this or any deployment pipeline based on this round's work; treat any
proposal to make cleanup destructive as a separate, explicitly-reviewed
change.

## 7. Abort conditions

Stop and do not proceed to the next step (or roll back if already deployed)
if any of the following occur:

- The pre-deployment backup fails, or restore verification (§1.3) fails or
  is skipped.
- `backend/uploads/` or `backend/feedback_private_uploads/` cannot be backed
  up completely.
- Any migration in the `039 → 040 → 041` chain fails or reports an
  unexpected `down_revision`/head mismatch.
- The moderator-role review for `041` (§2) has not been completed.
- The application fails to boot due to a missing or invalid
  `API_PUBLIC_BASE_URL`.
- Any post-deployment health or smoke check (§5) fails.
- Error rates or health checks degrade after rollout and do not recover
  quickly.

## 8. Application rollback order

Roll back in the reverse of the deploy order:

1. Redeploy the previous known-good `backend`/`web` application images.
2. Only after the previous application version is running and confirmed
   healthy, consider whether a database rollback (§9) is actually necessary —
   the previous application version is compatible with the post-`041` schema
   being present but unused, since a schema rollback is riskier than an
   application-only rollback.

## 9. Database restore criteria and procedure

Restore the database from the pre-deployment backup only if the schema
itself is the source of the problem (for example, a migration produced
incorrect data, or a schema change is incompatible with the rolled-back
application version in a way that breaks it) — not merely because the new
application version had an unrelated bug.

Procedure:

1. Stop write traffic to the affected database (e.g. take the `backend`
   service out of rotation or pause it).
2. Restore the verified backup (§1.3) into the production database using the
   same restore method validated during pre-deployment verification.
3. Confirm `alembic current` reports the expected pre-migration revision.
4. Restore `backend/uploads/` and `backend/feedback_private_uploads/` from
   their backups if their contents are inconsistent with the restored
   database state.
5. Redeploy the application version compatible with the restored schema
   revision.
6. Re-run the post-deployment health and smoke checks (§5) before resuming
   write traffic.
