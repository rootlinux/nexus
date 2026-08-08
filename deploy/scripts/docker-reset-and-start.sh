#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.yml"
LOCAL_COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.local.yml"
ENV_FILE="$ROOT_DIR/deploy/.env.docker"

if [[ "${CONFIRM_RESET_LOCAL_DB:-}" != "yes" ]]; then
  echo "Refusing to delete the local database volume." >&2
  echo "Re-run with CONFIRM_RESET_LOCAL_DB=yes only if a full local reset is intended." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  -f "$LOCAL_COMPOSE_FILE" \
  down -v --remove-orphans
docker compose --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  -f "$LOCAL_COMPOSE_FILE" \
  up -d --build
