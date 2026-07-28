#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.yml"
LOCAL_COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.local.yml"
ENV_FILE="$ROOT_DIR/deploy/.env.docker"

docker compose --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  -f "$LOCAL_COMPOSE_FILE" \
  up -d --build
