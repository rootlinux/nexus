#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INITDB_DIR="$ROOT_DIR/deploy/initdb"
OUTPUT_FILE="${OUTPUT_FILE:-$ROOT_DIR/tmp/deploy-local-schema.snapshot.sql}"
TMP_FILE="$OUTPUT_FILE.tmp"

SRC_PGHOST="${SRC_PGHOST:-localhost}"
SRC_PGPORT="${SRC_PGPORT:-5432}"
SRC_PGUSER="${SRC_PGUSER:-postgres}"
SRC_PGPASSWORD="${SRC_PGPASSWORD:-postgres}"
SRC_PGDATABASE="${SRC_PGDATABASE:-xplatform}"

mkdir -p "$INITDB_DIR"
mkdir -p "$(dirname "$OUTPUT_FILE")"

echo "Dumping schema-only PostgreSQL snapshot for $SRC_PGDATABASE from $SRC_PGHOST:$SRC_PGPORT ..."
PGPASSWORD="$SRC_PGPASSWORD" pg_dump \
  --host="$SRC_PGHOST" \
  --port="$SRC_PGPORT" \
  --username="$SRC_PGUSER" \
  --dbname="$SRC_PGDATABASE" \
  --schema-only \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --encoding=UTF8 \
  --file="$TMP_FILE"

mv "$TMP_FILE" "$OUTPUT_FILE"
echo "Schema-only snapshot refreshed at $OUTPUT_FILE"
