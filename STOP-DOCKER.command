#!/bin/bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${NEXUS_DOCKER_ENV_FILE:-$ROOT_DIR/deploy/.env.docker}"
COMPOSE=(docker compose --project-name deploy --env-file "$ENV_FILE" --file "$ROOT_DIR/deploy/docker-compose.yml" --file "$ROOT_DIR/deploy/docker-compose.local.yml")

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running; Nexus is already stopped."
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing file: $ENV_FILE" >&2
  exit 1
fi

"${COMPOSE[@]}" stop
echo "Nexus containers stopped. Volumes and uploaded files are preserved."
