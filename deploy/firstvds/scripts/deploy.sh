#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/bar-manager-ai}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/firstvds/.env}"
COMPOSE_FILE="$REPO_DIR/deploy/firstvds/docker-compose.yml"

cd "$REPO_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.example and fill secret values." >&2
  exit 1
fi

# Refuse deployment if obvious placeholders remain.
if grep -Eq '(^|=)(api\.example\.com|PROJECT_REF|DB_PASSWORD|REGION\.pooler)' "$ENV_FILE"; then
  echo "Environment file still contains placeholder values." >&2
  exit 1
fi

git fetch origin main
git checkout main
git reset --hard origin/main

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build --remove-orphans

docker image prune -f >/dev/null

API_DOMAIN="$(sed -n 's/^API_DOMAIN=//p' "$ENV_FILE" | tail -n 1)"
if [[ -z "$API_DOMAIN" ]]; then
  echo "API_DOMAIN is not configured" >&2
  exit 1
fi

for attempt in {1..24}; do
  if curl --fail --silent --show-error "https://${API_DOMAIN}/health" >/tmp/bar-manager-health.json; then
    cat /tmp/bar-manager-health.json
    echo
    echo "Deployment is healthy: https://${API_DOMAIN}/health"
    exit 0
  fi
  sleep 5
done

echo "Deployment did not become healthy. Recent logs:" >&2
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=150 >&2
exit 1
