#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bar-manager-ai}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/firstvds/.env}"
COMPOSE_FILE="$REPO_DIR/deploy/firstvds/docker-compose.yml"
MIGRATION_LOG="/tmp/bar-manager-migration.log"

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

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

# Stop the public stack before schema changes and build the current API image.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop caddy api >/dev/null 2>&1 || true
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" rm -f caddy api >/dev/null 2>&1 || true

# Remove abandoned one-off migration containers from interrupted deployments.
mapfile -t stale_migration_containers < <(
  docker ps -aq --filter "name=bar-manager-ai-api-run-"
)
if (( ${#stale_migration_containers[@]} > 0 )); then
  docker rm -f "${stale_migration_containers[@]}" >/dev/null 2>&1 || true
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build api

# Run migrations as a separate one-off job. Supabase Session Pooler can finish
# the SQL successfully but time out while asyncpg closes the connection. Accept
# only that exact post-success condition; all SQL and connection errors remain fatal.
echo "Running database migrations..."
rm -f "$MIGRATION_LOG"
set +e
timeout 300s docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  run --rm --no-deps api python -m app.migrate 2>&1 | tee "$MIGRATION_LOG"
migration_status=${PIPESTATUS[0]}
set -e

if (( migration_status != 0 )); then
  if grep -Eq '^Migration (already applied|applied): .+' "$MIGRATION_LOG" \
    && grep -q '^TimeoutError$' "$MIGRATION_LOG"; then
    echo "Migration completed; Supabase pooler close timeout was safely ignored."
  else
    echo "Database migration failed with status ${migration_status}." >&2
    exit "$migration_status"
  fi
fi

# Start the API only after migrations have completed successfully.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --force-recreate --remove-orphans

docker image prune -f >/dev/null

API_DOMAIN="$(sed -n 's/^API_DOMAIN=//p' "$ENV_FILE" | tail -n 1)"
if [[ -z "$API_DOMAIN" ]]; then
  echo "API_DOMAIN is not configured" >&2
  exit 1
fi

for attempt in {1..36}; do
  if curl --fail --silent --show-error "https://${API_DOMAIN}/health" >/tmp/bar-manager-health.json; then
    cat /tmp/bar-manager-health.json
    echo
    echo "Deployment is healthy: https://${API_DOMAIN}/health"
    exit 0
  fi
  sleep 5
done

echo "Deployment did not become healthy. Recent logs:" >&2
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200 >&2
exit 1
