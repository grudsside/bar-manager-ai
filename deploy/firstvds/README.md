# FirstVDS + Supabase deployment

## Architecture

- GitHub Pages serves the PWA frontend.
- FirstVDS runs FastAPI, Telegram webhook processing, scheduled jobs and Web Push delivery.
- Caddy terminates HTTPS and proxies only to the internal API container.
- Supabase provides PostgreSQL, private file storage and future single-owner authentication.
- The API container is not published directly to the internet.

## Recommended initial server

- Ubuntu 24.04 LTS
- 2 vCPU
- 4 GB RAM
- 40–50 GB NVMe
- one public IPv4 address

This is intentionally larger than the minimum so Telegram processing, OpenAI requests and scheduled workers can run without immediately resizing the VM.

## Supabase database connection

Use the **Session pooler** connection string on port `5432` and add `sslmode=require`. A persistent VM can keep a small application-side asyncpg pool, while the Session pooler avoids dependence on direct IPv6 connectivity.

Example format:

```text
postgresql://postgres.PROJECT_REF:PASSWORD@REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

Never commit the database password or Supabase service role key.

## First server setup

```bash
ssh root@SERVER_IP
git clone https://github.com/grudsside/bar-manager-ai.git /opt/bar-manager-ai
cd /opt/bar-manager-ai
bash deploy/firstvds/scripts/install-server.sh
cp deploy/firstvds/.env.example deploy/firstvds/.env
chmod 600 deploy/firstvds/.env
```

Fill `deploy/firstvds/.env`, point the API domain's DNS A record to the server, then run:

```bash
bash deploy/firstvds/scripts/deploy.sh
```

Expected health endpoint:

```text
https://API_DOMAIN/health
```

## GitHub deployment secrets

After the first successful manual release, add these repository environment secrets for `production`:

- `FIRSTVDS_HOST`
- `FIRSTVDS_USER`
- `FIRSTVDS_SSH_KEY`
- `FIRSTVDS_PORT` (optional, defaults to 22)

The SSH key should belong to a dedicated non-root deployment user. Set repository variable `FIRSTVDS_AUTO_DEPLOY=true` only after a manual workflow run succeeds.

## Operations

```bash
# Status
docker compose --env-file deploy/firstvds/.env -f deploy/firstvds/docker-compose.yml ps

# Logs
docker compose --env-file deploy/firstvds/.env -f deploy/firstvds/docker-compose.yml logs -f --tail=200

# Restart
docker compose --env-file deploy/firstvds/.env -f deploy/firstvds/docker-compose.yml restart

# Redeploy current main
bash deploy/firstvds/scripts/deploy.sh
```

Supabase remains the system of record, so rebuilding or replacing the FirstVDS VM does not delete application data.
