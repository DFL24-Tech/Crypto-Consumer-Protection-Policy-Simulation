# Dev-Env Compose Split + Standalone Nginx — Design

## Purpose

Today there is exactly one non-prod compose file, `docker-compose.yml`, meant
for loopback-bound laptop iteration. There is no path to run the whole stack
(postgres, minio, server, worker, and the new `web` app) on a shared,
long-lived VPS *without* going all the way to the full `docker-compose.prod.yml`
overlay (Caddy, real TLS/ACME, DNS, hardened secrets). This adds that middle
tier: a "dev env" — a real shared box, reachable by teammates over plain
HTTP behind nginx, without prod's TLS/hardening ceremony.

**Non-goals:** replacing Caddy/`docker-compose.prod.yml` for real production
(unchanged), automating certbot (the operator runs it by hand later), any
change to service definitions beyond restart policy and file location.

## File restructuring

- **Rename** `docker-compose.yml` → `docker-compose.local.yml`. Content
  unchanged — still loopback-bound (`127.0.0.1:<port>:<port>`), no restart
  policies, for ephemeral laptop dev. Every command that referenced the
  default filename now needs `-f docker-compose.local.yml`.
- **New `docker-compose.yml`** (reclaims the default name): the same five
  services as today's file (postgres, minio, server, worker, web), same
  loopback port bindings (nginx runs on the *same host*, so `127.0.0.1` is
  reachable — no need to bind `0.0.0.0` and expose containers directly to
  the internet), plus `restart: unless-stopped` on every service, since this
  variant is meant to run persistently on a shared VPS rather than being
  started/stopped by hand each session. No Caddy, no CPU/memory limits, no
  backup profile — genuinely minimal; those stay prod-only.
- **`docker-compose.prod.yml`** keeps layering on the (new) `docker-compose.yml`
  exactly as before (`-f docker-compose.yml -f docker-compose.prod.yml`) —
  its own `restart: unless-stopped` overrides for postgres/minio/server/worker
  become redundant now that the base file sets the same value, but Compose
  merges identical scalars without error, so no functional change; leaving
  them in place documents intent per-file and avoids touching the prod
  overlay's structure.
- **Reference updates** (grep-verified, no other hits in the repo): the
  `docker-compose.yml` mentions in `deploy/backup.sh` and `docs/DEPLOY.md`
  stay correct as-is (they already reference the *base* file's default name,
  which the new file still is) — no edits needed there. `web/README.md`'s
  `docker compose up web` also still works unchanged, since Compose still
  auto-discovers `docker-compose.yml` by default.

## Standalone nginx config

New file `deploy/nginx-dev.conf`, installed by the operator directly onto the
VPS's system nginx (`/etc/nginx/sites-available/`) — **not** a Dockerized
service, not part of any compose file. Three plain-HTTP `server` blocks,
proxying by hostname to the loopback ports the new `docker-compose.yml`
already publishes:

| Hostname (operator-chosen) | Proxies to |
|---|---|
| `$MCP_DEV_HOSTNAME` | `127.0.0.1:8000` (server) |
| `$WEB_DEV_HOSTNAME` | `127.0.0.1:3000` (web) |
| `$S3_DEV_HOSTNAME` | `127.0.0.1:9000` (minio) |

The MCP block carries the same streaming-friendly settings Caddy's prod
block uses (`proxy_buffering off`, `proxy_read_timeout` long enough for a
slow tool call, `proxy_http_version 1.1`), so Streamable HTTP works
identically to prod. No `listen 443` anywhere — plain `listen 80` blocks,
written so `certbot --nginx -d <hostname>` (run by the operator, out of
scope here) can upgrade each block to HTTPS in place without further editing.

A new `docs/DEV-ENV.md` documents the runbook: reuse `.env`'s existing
pattern (same vars as `docker-compose.local.yml` today — this variant needs
no new secrets, unlike the prod overlay), `docker compose up -d --build` (no
`-f` needed — this is the default file), install `deploy/nginx-dev.conf`
onto the VPS (filling in real hostnames), reload nginx, optionally run
certbot later. Kept separate from `docs/DEPLOY.md` so the real-production
runbook (Caddy/TLS/backups/DNS) stays focused and this lighter-weight path
doesn't dilute it.
