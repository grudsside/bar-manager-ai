#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: bash deploy/firstvds/scripts/configure-instance.sh" >&2
  exit 1
fi

REPO_DIR="${REPO_DIR:-/opt/bar-manager-ai}"
ENV_FILE="$REPO_DIR/deploy/firstvds/.env"
OWNER_KEY_FILE="/root/bar-manager-ai-owner-key.txt"
API_DOMAIN="uhalovgrigorij40731.fvds.ru"
FRONTEND_ORIGIN="https://grudsside.github.io"
SUPABASE_URL="https://oincykbznwhphqlrdcak.supabase.co"
STORAGE_BUCKET="bar-manager-files"

cd "$REPO_DIR"

printf '\nБар-менеджер AI — первоначальная настройка FirstVDS\n'
printf 'API domain: %s\n' "$API_DOMAIN"
printf 'Supabase: %s\n\n' "$SUPABASE_URL"

read -r -p "Вставьте Session pooler URL из Supabase: " POOLER_URL
if [[ -z "$POOLER_URL" ]]; then
  echo "Session pooler URL не указан" >&2
  exit 1
fi

if [[ "$POOLER_URL" == *"[YOUR-PASSWORD]"* || "$POOLER_URL" == *"YOUR_PASSWORD"* || "$POOLER_URL" == *"DB_PASSWORD"* ]]; then
  read -r -s -p "Введите пароль базы Supabase: " DB_PASSWORD_RAW
  echo
  if [[ -z "$DB_PASSWORD_RAW" ]]; then
    echo "Пароль базы не указан" >&2
    exit 1
  fi
  DATABASE_URL="$({ POOLER_TEMPLATE="$POOLER_URL" DB_PASSWORD_RAW="$DB_PASSWORD_RAW" python3 - <<'PY'
import os
from urllib.parse import quote_plus

template = os.environ["POOLER_TEMPLATE"]
password = quote_plus(os.environ["DB_PASSWORD_RAW"])
for marker in ("[YOUR-PASSWORD]", "YOUR_PASSWORD", "DB_PASSWORD"):
    template = template.replace(marker, password)
print(template)
PY
  } )"
else
  DATABASE_URL="$POOLER_URL"
fi

if [[ "$DATABASE_URL" != postgresql://* && "$DATABASE_URL" != postgres://* ]]; then
  echo "Строка подключения должна начинаться с postgresql:// или postgres://" >&2
  exit 1
fi

if [[ "$DATABASE_URL" != *"sslmode="* ]]; then
  if [[ "$DATABASE_URL" == *"?"* ]]; then
    DATABASE_URL="${DATABASE_URL}&sslmode=require"
  else
    DATABASE_URL="${DATABASE_URL}?sslmode=require"
  fi
fi

OWNER_API_KEY="$(openssl rand -hex 32)"

read -r -s -p "Supabase service_role key (можно оставить пустым до подключения файлов): " SUPABASE_SERVICE_ROLE_KEY
printf '\n'

TMP_ENV="$(mktemp)"
chmod 600 "$TMP_ENV"
cat >"$TMP_ENV" <<EOF
API_DOMAIN=$API_DOMAIN
FRONTEND_ORIGIN=$FRONTEND_ORIGIN
DATABASE_URL=$DATABASE_URL
OWNER_API_KEY=$OWNER_API_KEY
OPENAI_API_KEY=
OPENAI_MODEL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
OWNER_TELEGRAM_ID=
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
SUPABASE_URL=$SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=$STORAGE_BUCKET
EOF

install -m 600 "$TMP_ENV" "$ENV_FILE"
rm -f "$TMP_ENV"
printf '%s\n' "$OWNER_API_KEY" >"$OWNER_KEY_FILE"
chmod 600 "$OWNER_KEY_FILE"

bash deploy/firstvds/scripts/install-server.sh
bash deploy/firstvds/scripts/deploy.sh

printf '\nНастройка завершена.\n'
printf 'Health: https://%s/health\n' "$API_DOMAIN"
printf 'Ключ владельца сохранён только на сервере: %s\n' "$OWNER_KEY_FILE"
printf 'Показать его позже: cat %s\n' "$OWNER_KEY_FILE"
printf 'Не отправляйте этот ключ в чат и не добавляйте его в GitHub.\n'
