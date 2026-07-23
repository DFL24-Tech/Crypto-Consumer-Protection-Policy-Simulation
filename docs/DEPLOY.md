# Production deployment & runbook

The full stack — MCP/REST API, worker, Postgres, MinIO, and the AuthKit web
login app — on a single dedicated-CPU VPS, fronted by
[Caddy](https://caddyserver.com) for automatic TLS and stable public
hostnames.

```
     https://mcp.example.com   https://artifacts.example.com   https://web.example.com
              │                          │                              │
         ┌────▼──────────────────────── Caddy ──────────────────────────▼────┐
         │                       (TLS, reverse proxy)                        │
         └────┬───────────────────────────────┬─────────────────────┬───────┘
              │ server:8000                    │ minio:9000          │ web:3000
         ┌────▼────┐   ┌────────┐   ┌──────────▼──┐   ┌───────────┐  ┌──▼──┐
         │ server  │   │ worker │   │    minio    │   │ postgres  │  │ web │
         └────┬────┘   └───┬────┘   └─────────────┘   └───────────┘  └─────┘
              └── jobs ────┴──────────► (queue + store)
```

Everything below runs from the repository root on the VPS. The production
overlay is `docker-compose.prod.yml`; secrets and hostnames come from
`.env.prod` (never committed — see `.env.prod.example`).

Set up your shell once per session. `--env-file` passes variables to Compose
and the containers, **not** to your shell, so also source the file — several
commands below expand `$POSTGRES_USER`, `$MINIO_BUCKET`, `$MCP_HOSTNAME`, etc.
in the host shell:

```sh
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod"
set -a; . ./.env.prod; set +a          # export the vars into this shell too
```

## One-time setup (human)

These steps need a person: they involve buying the box, DNS, and secrets.

1. **VPS** — a dedicated-CPU instance (≥4 cores, ≥8 GB RAM), Docker Engine +
   Compose v2 installed. Open inbound 80 and 443 only.
2. **DNS** — point all three hostnames at the VPS (A/AAAA):
   - `MCP_HOSTNAME` → the MCP endpoint (e.g. `mcp.example.com`)
   - `S3_HOSTNAME` → the artifact endpoint (e.g. `artifacts.example.com`)
   - `WEB_HOSTNAME` → the AuthKit login app (e.g. `web.example.com`)
   Caddy provisions certificates on first start via the ACME HTTP challenge,
   so DNS must resolve *before* `up`.
3. **WorkOS** — create a production AuthKit environment, enable Dynamic Client
   Registration, and add `https://<MCP_HOSTNAME>/oauth2/callback` as a
   redirect (see `server/dfl24sim_server/auth.py`). Also add
   `https://<WEB_HOSTNAME>/callback` as a redirect for the `web/` app's hosted
   login (see `web/README.md`) — same WorkOS project, different SDK/flow.
4. **Secrets** — `cp .env.prod.example .env.prod`, then fill in real values:
   long random `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD`, all three
   hostnames, `SERVER_BASE_URL=https://<MCP_HOSTNAME>`,
   `MINIO_PUBLIC_URL=https://<S3_HOSTNAME>`, `AUTHKIT_DOMAIN`, and the web
   app's `WORKOS_CLIENT_ID` / `WORKOS_API_KEY` / `WORKOS_COOKIE_PASSWORD` /
   `WEB_REDIRECT_URI=https://<WEB_HOSTNAME>/callback`. Set `WORKER_CPUS` to
   about (cores − 1) so a running study leaves the API and Postgres a core.
   `chmod 600 .env.prod`.

## Deploy a new version

```sh
git pull
$COMPOSE up -d --build          # rebuild images, recreate changed services
$COMPOSE ps                     # all services Up; server healthy
curl -fsS https://$MCP_HOSTNAME/health   # -> {"status":"ok"}
```

The `migrate` service runs the schema migration to completion before `server`
and `worker` start; schema changes are additive (`ADD COLUMN IF NOT EXISTS`),
so a rolling redeploy is safe.

**Smoke test the analyst path** after deploy: add the server as a Claude
custom connector (OAuth via AuthKit should complete), run a sync scenario,
trigger `run_study`, then `get_job_status` → `get_job_result` → `get_artifact`
and confirm the returned URL serves the figure.

## Roll back

Images are rebuilt from the checkout, so rolling back is checking out the prior
revision and rebuilding:

```sh
git checkout <previous-tag-or-sha>
$COMPOSE up -d --build
```

Because migrations are additive, an older image keeps working against the newer
schema; no down-migration is needed. If a specific service is wedged, recreate
just it: `$COMPOSE up -d --force-recreate --no-deps server`.

## Logs

```sh
$COMPOSE logs -f server          # API / MCP requests
$COMPOSE logs -f worker          # job execution
$COMPOSE logs -f caddy           # TLS provisioning, proxy errors
$COMPOSE logs --since 15m server worker
```

## Re-run a stuck job

Jobs run on the worker and are tracked in `sim_jobs`. If one is wedged
(`running` long past plausible, or the worker was killed mid-job):

1. Inspect it — from any MCP client call `get_job_status` with the id, or query
   directly:
   ```sh
   $COMPOSE exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT id, job_type, status, started_at FROM sim_jobs ORDER BY created_at DESC LIMIT 10;"
   ```
2. Restart the worker to pick the queue back up (procrastinate re-runs jobs
   that were interrupted before completion):
   ```sh
   $COMPOSE restart worker
   ```
3. If the row is stuck in `running` but no longer queued (the worker died after
   claiming it), mark it failed so the org's quota frees and the analyst can
   re-trigger; then re-run from the client with `force=true`:
   ```sh
   $COMPOSE exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "UPDATE sim_jobs SET status='failed', error='manually reset', finished_at=now() WHERE id='<job-id>' AND status='running';"
   ```

## Backups

`deploy/backup.sh` dumps Postgres (compressed, timestamped, retained
`BACKUP_KEEP_DAYS`) and mirrors the MinIO artifact bucket into `$BACKUP_DIR`.
Schedule it from the host crontab:

```cron
0 3 * * *  cd /srv/dfl24sim && deploy/backup.sh >> /var/log/dfl24-backup.log 2>&1
```

Copy `$BACKUP_DIR` off-box (another provider) on its own schedule — a backup on
the same VPS does not survive losing the VPS.

### Restore

```sh
# Postgres: recreate an empty store, then load a dump
$COMPOSE up -d postgres
gzip -dc backups/pg-<timestamp>.sql.gz | \
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# MinIO: create the bucket if the store is fresh, then push the mirror back
$COMPOSE --profile backup run --rm --entrypoint sh minio-backup -c \
  'mc mb --ignore-existing store/'"$MINIO_BUCKET"' && mc mirror --overwrite /backups/minio/'"$MINIO_BUCKET"' store/'"$MINIO_BUCKET"
```

## Data persistence

Postgres (`pgdata`), MinIO (`miniodata`), and Caddy's certificates
(`caddydata`) are named volumes; they survive `docker compose down` and
`up`. **`down -v` deletes them** — never use `-v` in production. All host
ports bind to `127.0.0.1`, so Postgres and MinIO are never exposed on the
public interface; reach them for maintenance over an SSH tunnel.
