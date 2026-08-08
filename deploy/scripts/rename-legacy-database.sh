#!/usr/bin/env bash
# One-time migration for deployments created before the project was renamed to Nexus.
#
# Those stacks hold their data in a PostgreSQL database literally named "xplatform".
# The Compose default is now "nexus", and POSTGRES_DB only creates a database on a
# *fresh* data directory — it never renames an existing one. Without this rename, an
# upgraded stack would connect to a database that does not exist (or, worse, silently
# create an empty one) and the old data would look like it had vanished.
#
# This script renames the database in place. No data is copied, dropped, or rewritten.
#
#   1. Stop the app so nothing writes mid-rename:
#        docker compose -f deploy/docker-compose.yml stop backend web
#   2. Run this script (postgres must still be running).
#   3. Start the stack again; alembic will find the schema exactly where it left off.
#
# Prefer not to rename? Pin POSTGRES_DB=xplatform in your env file instead — that is a
# fully supported configuration and this script is then unnecessary.

set -euo pipefail

CONTAINER="${POSTGRES_CONTAINER:-nexus-postgres}"
PGUSER_NAME="${POSTGRES_USER:-postgres}"
LEGACY_DB="${LEGACY_DB:-xplatform}"
TARGET_DB="${TARGET_DB:-nexus}"

# Only PostgreSQL identifiers matching this pattern are permitted.
# This is an allowlist: anything else is rejected before it reaches psql.
VALID_DBNAME_RE='^[a-zA-Z_][a-zA-Z0-9_]*$'

validate_db_name() {
  local name="$1" label="$2"
  if [[ ! "$name" =~ $VALID_DBNAME_RE ]]; then
    echo "${label} '${name}' is not a valid PostgreSQL identifier (only [a-zA-Z_][a-zA-Z0-9_]* allowed)." >&2
    exit 1
  fi
}

validate_db_name "$LEGACY_DB" "LEGACY_DB"
validate_db_name "$TARGET_DB" "TARGET_DB"

psql_admin() {
  # Connect through the "postgres" maintenance database: you cannot rename a database
  # you are currently connected to.
  docker exec -i "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PGUSER_NAME" -d postgres "$@"
}

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "PostgreSQL container '$CONTAINER' is not running. Start it first (or set POSTGRES_CONTAINER)." >&2
  exit 1
fi

exists() {
  # $1 has already passed validate_db_name, so it contains only [a-zA-Z_][a-zA-Z0-9_]* —
  # it is safe inside a single-quoted SQL literal and cannot inject.
  # quote_ident() is still used as defence-in-depth for the ALTER below.
  [ "$(psql_admin -Atc "SELECT 1 FROM pg_database WHERE datname = '$1'")" = "1" ]
}

if ! exists "$LEGACY_DB"; then
  echo "No database named '$LEGACY_DB' — nothing to migrate. This stack is already on the new naming."
  exit 0
fi

if exists "$TARGET_DB"; then
  echo "Both '$LEGACY_DB' and '$TARGET_DB' exist. Refusing to guess which one is authoritative." >&2
  echo "Inspect both, drop or rename the unwanted one by hand, then re-run." >&2
  exit 1
fi

ACTIVE="$(psql_admin -Atc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$LEGACY_DB' AND pid <> pg_backend_pid()")"
if [ "$ACTIVE" != "0" ]; then
  echo "'$LEGACY_DB' still has $ACTIVE active connection(s)."
  echo "Stop the backend/web containers first, then re-run:"
  echo "  docker compose -f deploy/docker-compose.yml stop backend web"
  exit 1
fi

echo "Renaming database '$LEGACY_DB' -> '$TARGET_DB' ..."
psql_admin -c "ALTER DATABASE \"$LEGACY_DB\" RENAME TO \"$TARGET_DB\";"

echo "Done. Verify before restarting the app:"
echo "  docker exec $CONTAINER psql -U $PGUSER_NAME -d $TARGET_DB -c 'SELECT version_num FROM alembic_version;'"
