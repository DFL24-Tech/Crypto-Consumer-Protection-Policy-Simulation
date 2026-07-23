# Dev-env deployment (shared VPS, no TLS ceremony)

A lighter-weight alternative to [`docs/DEPLOY.md`](DEPLOY.md)'s full
production runbook: run the whole stack (postgres, minio, server, worker,
web) persistently on a shared VPS, fronted by plain HTTP nginx instead of
Caddy/ACME/DNS-gated TLS. Good for a team staging box; not for real
production traffic (see `docs/DEPLOY.md` for that).

## One-time setup

1. **VPS** — any box with Docker Engine + Compose v2 installed.
2. **Secrets** — `cp .env.example .env`, fill in real values the same way
   you would for local dev (see `.env.example`'s comments). No new secrets
   are needed beyond what `docker-compose.local.yml` already uses, but do
   set `WEB_REDIRECT_URI=http://<web-hostname-you-chose>/callback` (e.g.
   `http://web-dev.example.com/callback`) — it's baked into the `web` image
   at build time, so the default `http://localhost:3000/callback` only
   works if you're testing from the VPS itself. Add that same URL as an
   allowed redirect in the WorkOS dashboard (see `web/README.md`).
3. **Nginx** — copy `deploy/nginx-dev.conf` to the VPS (e.g.
   `/etc/nginx/sites-available/dfl24sim-dev`), replace the three
   `server_name` placeholders with real hostnames, symlink it into
   `sites-enabled`, then `nginx -s reload`. Point DNS at the VPS for each
   hostname you chose.

## Deploy

```sh
git pull
docker compose up -d --build   # no -f needed — docker-compose.yml is the default
docker compose ps              # all services Up; server/web/minio healthy
curl -fsS http://127.0.0.1:8000/health   # -> {"status":"ok"}
curl -fsS http://127.0.0.1:3000/health   # -> {"status":"ok"}
```

Every service has `restart: unless-stopped`, so the stack survives a VPS
reboot or an individual container crash without manual intervention —
`migrate` is the one exception, since it's meant to run once per deploy and
exit.

## Add TLS later

Once DNS resolves and you're ready for HTTPS, run `certbot --nginx -d
<hostname>` once per hostname in `deploy/nginx-dev.conf` — the certbot nginx
plugin edits the matching `server` block in place to add `listen 443 ssl`
and the certificate paths; no manual editing of the proxy rules needed.

## Relationship to other compose files

- `docker-compose.local.yml` — ephemeral laptop dev, no restart policies.
- `docker-compose.yml` (this doc) — same services, persistent, fronted by
  this doc's standalone nginx config.
- `docker-compose.yml` + `docker-compose.prod.yml` — real production, fronted
  by Caddy with automatic TLS; see `docs/DEPLOY.md`.
