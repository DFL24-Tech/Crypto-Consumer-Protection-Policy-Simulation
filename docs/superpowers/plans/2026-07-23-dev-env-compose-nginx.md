# Dev-Env Compose Split + Standalone Nginx Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split today's single dev compose file into `docker-compose.local.yml` (ephemeral laptop dev, unchanged behavior) and a new `docker-compose.yml` (the same services, persistent — `restart: unless-stopped` — for a shared "dev env" VPS), plus a standalone nginx config so that VPS can front the stack over plain HTTP without the full Caddy/TLS production ceremony.

**Architecture:** `git mv docker-compose.yml docker-compose.local.yml` preserves history. The new `docker-compose.yml` is `docker-compose.local.yml`'s content with `restart: unless-stopped` added to every long-running service (not `migrate`, which is a one-shot job). `docker-compose.prod.yml` is untouched — it already targets the default filename, which is now the restart-policy-bearing file, so its own `up`/`--env-file .env.prod` flow is unaffected. `deploy/nginx-dev.conf` is a standalone (non-Dockerized) nginx config for the VPS's system nginx, reverse-proxying by hostname to the loopback ports `docker-compose.yml` already publishes.

**Tech Stack:** Docker Compose YAML, nginx config syntax, Markdown docs.

## Global Constraints

- Never run `git commit` during task execution — task work stays uncommitted, staged with `git add` only. (The controller will commit everything at the very end, per explicit instruction for this round of work — but that happens after this plan's tasks and their reviews are complete, not during any individual task.)
- Do not add `restart: unless-stopped` to the `migrate` service — it is a one-shot job that must run to completion and exit 0; a restart policy on it would create a restart loop.
- Do not modify `docker-compose.prod.yml`, `deploy/Caddyfile`, or `docs/DEPLOY.md` — this plan only adds the new dev-env path alongside them, unchanged.
- `docker-compose.local.yml` must remain byte-for-byte identical in service content to today's `docker-compose.yml` (only the filename changes) — no drive-by edits.

---

### Task 1: Rename the local dev compose file

**Files:**
- Rename: `docker-compose.yml` → `docker-compose.local.yml`

**Interfaces:**
- Produces: `docker-compose.local.yml`, usable exactly as `docker-compose.yml` was (`docker compose -f docker-compose.local.yml up`), with identical service definitions (postgres, minio, migrate, server, web, worker) and their `x-db-env`/`x-auth-env`/`x-s3-env`/`x-web-env` anchors.

- [ ] **Step 1: Rename with git mv to preserve history**

```bash
git mv docker-compose.yml docker-compose.local.yml
```

- [ ] **Step 2: Verify content is unchanged, only the path moved**

```bash
git diff --cached --stat
```
Expected: shows a rename (`docker-compose.yml => docker-compose.local.yml`) with 0 or near-0 changed lines — git detects pure renames automatically when content is identical.

- [ ] **Step 3: Validate the renamed file still works standalone**

```bash
docker compose -f docker-compose.local.yml config >/dev/null
```
Expected: exits 0, no error.

- [ ] **Step 4: Stage (already staged by git mv, confirm)**

```bash
git status --short | grep docker-compose
```
Expected: shows `R  docker-compose.yml -> docker-compose.local.yml`. Do NOT commit.

---

### Task 2: New minimal `docker-compose.yml` with persistent restart policies

**Files:**
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `docker-compose.local.yml` from Task 1 as the content template.
- Produces: a `docker-compose.yml` that `docker-compose.prod.yml` can still layer on top of unchanged (`docker compose -f docker-compose.yml -f docker-compose.prod.yml ...`), since `docker-compose.prod.yml` already assumes a base file with these five service names and the same env-var anchor names.

- [ ] **Step 1: Create `docker-compose.yml` as a copy of `docker-compose.local.yml`**

```bash
cp docker-compose.local.yml docker-compose.yml
```

- [ ] **Step 2: Update the file's header comment**

Find:
```yaml
# Dev defaults live in the ${VAR:-default} fallbacks; override via a .env file
# (see .env.example) — never by editing this file.
```
Replace with:
```yaml
# Minimal persistent stack for a shared "dev env" VPS — same services as
# docker-compose.local.yml (laptop dev), plus restart policies since this
# variant is meant to stay up between sessions. No TLS/Caddy here: front it
# with the standalone deploy/nginx-dev.conf on the VPS's system nginx (see
# docs/DEV-ENV.md). For real production with Caddy/TLS, layer
# docker-compose.prod.yml on top of this file instead, per docs/DEPLOY.md.
# Dev defaults live in the ${VAR:-default} fallbacks; override via a .env file
# (see .env.example) — never by editing this file.
```

- [ ] **Step 3: Add `restart: unless-stopped` to `postgres`**

Find:
```yaml
  postgres:
    image: postgres:16-alpine
    environment:
```
Replace with:
```yaml
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
```

- [ ] **Step 4: Add `restart: unless-stopped` to `minio`**

Find:
```yaml
  minio:
    image: minio/minio
    command: ["server", "/data", "--console-address", ":9001"]
    environment:
```
Replace with:
```yaml
  minio:
    image: minio/minio
    restart: unless-stopped
    command: ["server", "/data", "--console-address", ":9001"]
    environment:
```

- [ ] **Step 5: Add `restart: unless-stopped` to `server`**

Find:
```yaml
  server:
    build:
      context: .
      dockerfile: server/Dockerfile
    ports:
      # loopback-only: Caddy reaches the app over the compose network as
      # server:8000 and terminates TLS; the host port is for local access only
      - "127.0.0.1:8000:8000"
```
Replace with:
```yaml
  server:
    build:
      context: .
      dockerfile: server/Dockerfile
    restart: unless-stopped
    ports:
      # loopback-only: a same-host reverse proxy (nginx here, Caddy in real
      # prod) reaches this over the compose network as server:8000; the host
      # port is for same-host access only
      - "127.0.0.1:8000:8000"
```

- [ ] **Step 6: Add `restart: unless-stopped` to `web`**

Find:
```yaml
  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    ports:
      # loopback-only, same convention as server/postgres/minio
      - "127.0.0.1:3000:3000"
```
Replace with:
```yaml
  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    restart: unless-stopped
    ports:
      # loopback-only, same convention as server/postgres/minio
      - "127.0.0.1:3000:3000"
```

- [ ] **Step 7: Add `restart: unless-stopped` to `worker`**

Find:
```yaml
  worker:
    build:
      context: .
      dockerfile: server/Dockerfile
    command: ["python", "-m", "dfl24sim_server.worker"]
```
Replace with:
```yaml
  worker:
    build:
      context: .
      dockerfile: server/Dockerfile
    restart: unless-stopped
    command: ["python", "-m", "dfl24sim_server.worker"]
```

- [ ] **Step 8: Confirm `migrate` was NOT touched**

```bash
grep -A2 "^  migrate:" docker-compose.yml
```
Expected: no `restart:` line appears under `migrate:` — it must stay a one-shot job.

- [ ] **Step 9: Validate the new file alone, and layered under the prod overlay**

```bash
docker compose -f docker-compose.yml config >/dev/null && echo "base OK"
WEB_HOSTNAME=web.example.com MCP_HOSTNAME=mcp.example.com S3_HOSTNAME=s3.example.com \
POSTGRES_PASSWORD=x MINIO_ROOT_PASSWORD=x \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null && echo "prod-layered OK"
```
Expected: both print their `OK` line.

- [ ] **Step 10: Live-verify a persistent service actually restarts**

```bash
docker compose up -d --build postgres
docker kill $(docker compose ps -q postgres)
sleep 8
docker compose ps postgres
```
Expected: `STATUS` shows the container running again (Compose's `restart: unless-stopped` brought it back after the kill), not `Exited`. Tear down afterward:
```bash
docker compose down
```

- [ ] **Step 11: Stage (do not commit)**

```bash
git add docker-compose.yml
```

---

### Task 3: Standalone nginx config for the dev-env VPS

**Files:**
- Create: `deploy/nginx-dev.conf`

**Interfaces:**
- Consumes: the loopback ports `docker-compose.yml` (Task 2) publishes: `127.0.0.1:8000` (server), `127.0.0.1:3000` (web), `127.0.0.1:9000` (minio).
- Produces: a config file the operator installs directly on the VPS's system nginx (not part of any compose file, not consumed by any other task).

- [ ] **Step 1: Create `deploy/nginx-dev.conf`**

```nginx
# deploy/nginx-dev.conf — standalone reverse proxy for a shared "dev env"
# VPS. NOT part of docker-compose and NOT built into any image; install
# directly on the VPS's system nginx (e.g. copy to
# /etc/nginx/sites-available/dfl24sim-dev, symlink into sites-enabled,
# `nginx -s reload`). Proxies to the loopback ports docker-compose.yml
# already publishes on this same host — see docs/DEV-ENV.md.
#
# Replace the three server_name placeholders with real hostnames, point DNS
# at this VPS, then optionally run `certbot --nginx -d <hostname>` once per
# block to upgrade it to HTTPS in place — no other edits needed here.

server {
	listen 80;
	server_name mcp-dev.example.com;

	# Streamable HTTP keeps long-lived request/response streams; don't
	# buffer them, and allow ample time for a slow tool call to stream back
	# (matches deploy/Caddyfile's flush_interval -1 / 5m timeout for prod).
	proxy_buffering off;
	proxy_http_version 1.1;
	proxy_read_timeout 300s;

	location / {
		proxy_pass http://127.0.0.1:8000;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}

server {
	listen 80;
	server_name web-dev.example.com;

	location / {
		proxy_pass http://127.0.0.1:3000;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}

server {
	listen 80;
	server_name s3-dev.example.com;

	location / {
		proxy_pass http://127.0.0.1:9000;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}
```

- [ ] **Step 2: Lint the config's syntax with a throwaway nginx container**

Docker is available in this environment; this validates syntax without needing nginx installed on the host:
```bash
docker run --rm \
  -v "$(pwd)/deploy/nginx-dev.conf:/etc/nginx/conf.d/dev.conf:ro" \
  nginx:alpine nginx -t
```
Expected: output ends with `nginx: configuration file /etc/nginx/nginx.conf test is successful`.

- [ ] **Step 3: Stage (do not commit)**

```bash
git add deploy/nginx-dev.conf
```

---

### Task 4: `docs/DEV-ENV.md` runbook

**Files:**
- Create: `docs/DEV-ENV.md`

**Interfaces:**
- Consumes: `docker-compose.yml` (Task 2), `deploy/nginx-dev.conf` (Task 3).
- Produces: nothing consumed elsewhere — a standalone doc.

- [ ] **Step 1: Create `docs/DEV-ENV.md`**

```markdown
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
   are needed beyond what `docker-compose.local.yml` already uses.
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
```

- [ ] **Step 2: Stage (do not commit)**

```bash
git add docs/DEV-ENV.md
```

---

## Self-Review Notes

- **Spec coverage:** file rename (Task 1), new persistent base file (Task 2), standalone nginx config (Task 3), runbook doc (Task 4) — all four pieces the design specifies are covered.
- **Placeholder scan:** no TBD/TODO. The nginx config's `*.example.com` hostnames and the runbook's generic instructions are intentional operator-fill-in placeholders, called out explicitly as such in both files' own comments — not planning placeholders.
- **Type consistency:** service names (`postgres`, `minio`, `server`, `web`, `worker`, `migrate`) and their loopback ports (8000, 3000, 9000) are used identically across Task 2's compose file, Task 3's nginx config, and Task 4's doc. `migrate` is explicitly excluded from restart policies in both the plan text and a dedicated verification step (Task 2 Step 8), preventing the one real correctness risk in this change (a one-shot job restart-looping).
