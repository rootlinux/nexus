#!/bin/bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TIMEOUT_SECONDS="${DOCKER_START_TIMEOUT:-240}"
ENV_FILE="${NEXUS_DOCKER_ENV_FILE:-$ROOT_DIR/deploy/.env.docker}"
COMPOSE=(docker compose --project-name deploy --env-file "$ENV_FILE" --file "$ROOT_DIR/deploy/docker-compose.yml" --file "$ROOT_DIR/deploy/docker-compose.local.yml")

show_failure() {
  echo
  echo "Nexus failed to start. Container summary:" >&2
  "${COMPOSE[@]}" ps >&2 || true
  echo "Recent logs:" >&2
  "${COMPOSE[@]}" logs --no-color --tail 80 >&2 || true
}
trap show_failure ERR

if [[ ! -f "$ENV_FILE" || -L "$ENV_FILE" ]]; then
  echo "Missing file: $ENV_FILE" >&2
  echo "Copy the example and fill in unique local values:" >&2
  echo "  cp '$ROOT_DIR/deploy/.env.local-smoke.example' '$ENV_FILE'" >&2
  exit 1
fi

if [[ ! -O "$ENV_FILE" || "$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE" 2>/dev/null)" != "600" ]]; then
  echo "Unsafe .env.docker: it must be a regular file you own, with mode 0600." >&2
  echo "Fix it with: chmod 600 '$ENV_FILE'" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/backend/uploads" "$ROOT_DIR/backend/feedback_private_uploads"
chmod 700 "$ROOT_DIR/backend/feedback_private_uploads"
find "$ROOT_DIR/backend/feedback_private_uploads" -type d -exec chmod 700 {} +
find "$ROOT_DIR/backend/feedback_private_uploads" -type f -exec chmod 600 {} +

if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker
  deadline=$((SECONDS + TIMEOUT_SECONDS))
  until docker info >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Docker daemon was not ready within ${TIMEOUT_SECONDS} seconds." >&2
      exit 1
    fi
    sleep 2
  done
fi

echo "Building Nexus Docker images..."
"${COMPOSE[@]}" up -d --build

deadline=$((SECONDS + TIMEOUT_SECONDS))
services=( $("${COMPOSE[@]}" config --services) )
while true; do
  all_ready=true
  for service in "${services[@]}"; do
    container_id="$("${COMPOSE[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      all_ready=false
      break
    fi
    read -r state health < <(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")
    if [[ "$state" != "running" || ( "$health" != "healthy" && "$health" != "none" ) ]]; then
      all_ready=false
      break
    fi
  done
  $all_ready && break
  if (( SECONDS >= deadline )); then
    echo "Nexus services were not ready within ${TIMEOUT_SECONDS} seconds." >&2
    exit 1
  fi
  sleep 2
done

curl --fail --silent --show-error --max-time 10 http://app.nexus.localtest.me/ >/dev/null
curl --fail --silent --show-error --max-time 10 http://api.nexus.localtest.me/ready >/dev/null
trap - ERR
echo "Nexus is ready: http://app.nexus.localtest.me"
if [[ "${DOCKER_LAUNCH_NO_OPEN:-0}" != "1" ]]; then
  open http://app.nexus.localtest.me
fi
