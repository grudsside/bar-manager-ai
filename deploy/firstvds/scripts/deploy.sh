#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bar-manager-ai}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/firstvds/.env}"
COMPOSE_FILE="$REPO_DIR/deploy/firstvds/docker-compose.yml"
MIGRATION_LOG="/tmp/bar-manager-migration.log"
HEALTH_FILE="/tmp/bar-manager-health.json"

cd "$REPO_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.example and fill secret values." >&2
  exit 1
fi

if grep -Eq '(^|=)(api\.example\.com|PROJECT_REF|DB_PASSWORD|REGION\.pooler)' "$ENV_FILE"; then
  echo "Environment file still contains placeholder values." >&2
  exit 1
fi

git fetch origin main
git checkout main
git reset --hard origin/main

RELEASE_VERSION="$(git rev-parse --short=12 HEAD)"
export APP_VERSION="$RELEASE_VERSION"
echo "Preparing release ${RELEASE_VERSION}"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

# Build and migrate without stopping the running public stack. The current API
# and Caddy remain available until every migration has completed successfully.
# A failed migration therefore leaves the last healthy release online.
mapfile -t stale_migration_containers < <(
  docker ps -aq --filter "name=bar-manager-ai-api-run-"
)
if (( ${#stale_migration_containers[@]} > 0 )); then
  docker rm -f "${stale_migration_containers[@]}" >/dev/null 2>&1 || true
fi

# A clean build plus a commit-specific APP_VERSION prevents Docker from silently
# reusing an older API image after a source update.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  build --pull --no-cache api

echo "Running database migrations..."
rm -f "$MIGRATION_LOG"
set +e
timeout 300s docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  run --rm --no-deps api python -m app.migrate 2>&1 | tee "$MIGRATION_LOG"
migration_status=${PIPESTATUS[0]}
set -e

if (( migration_status != 0 )); then
  migration_count="$(
    sed -nE 's/^Discovered ([0-9]+) migration\(s\)$/\1/p' "$MIGRATION_LOG" | tail -n 1
  )"
  completed_count="$(
    grep -Ecx 'Migration (already applied|applied): .+' "$MIGRATION_LOG" || true
  )"

  if [[ "$migration_count" =~ ^[0-9]+$ ]] \
    && (( completed_count == migration_count )) \
    && { (( migration_status == 124 )) || grep -q '^TimeoutError$' "$MIGRATION_LOG"; }; then
    echo "Migration completed; Supabase pooler close timeout was safely ignored."
  else
    echo "Database migration failed with status ${migration_status}." >&2
    exit "$migration_status"
  fi
fi

# Replace the API only after migrations have completed. Caddy stays online and
# reconnects to the new healthy container.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  up -d --force-recreate --no-deps api

for attempt in {1..40}; do
  container_status="$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      bar-manager-ai-api 2>/dev/null || true
  )"
  if [[ "$container_status" == "healthy" ]]; then
    break
  fi
  if (( attempt == 40 )); then
    echo "API container did not become healthy." >&2
    docker logs --tail=200 bar-manager-ai-api >&2
    exit 1
  fi
  sleep 3
done

container_version="$(docker exec bar-manager-ai-api printenv APP_VERSION)"
if [[ "$container_version" != "$RELEASE_VERSION" ]]; then
  echo "Wrong API image is running: expected ${RELEASE_VERSION}, got ${container_version}." >&2
  exit 1
fi

docker image prune -f >/dev/null

API_DOMAIN="$(sed -n 's/^API_DOMAIN=//p' "$ENV_FILE" | tail -n 1)"
if [[ -z "$API_DOMAIN" ]]; then
  echo "API_DOMAIN is not configured" >&2
  exit 1
fi

for attempt in {1..36}; do
  if curl --fail --silent --show-error "https://${API_DOMAIN}/health" >"$HEALTH_FILE"; then
    if python3 - "$HEALTH_FILE" "$RELEASE_VERSION" <<'PY'
import json
import sys
from pathlib import Path

health_path = Path(sys.argv[1])
expected = sys.argv[2]
data = json.loads(health_path.read_text(encoding="utf-8"))
actual = data.get("version")
if actual != expected:
    raise SystemExit(f"Health version mismatch: expected {expected}, got {actual}")
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
    then
      echo "Deployment is healthy and verified: release ${RELEASE_VERSION}"
      exit 0
    fi
  fi
  sleep 5
done

echo "Deployment did not expose the expected release. Recent logs:" >&2
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200 >&2
exit 1
