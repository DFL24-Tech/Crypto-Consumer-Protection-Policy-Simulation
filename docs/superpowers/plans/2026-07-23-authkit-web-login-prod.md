# AuthKit Web Login — Production Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `web` app (built in `docs/superpowers/plans/2026-07-23-authkit-web-login.md`) into the production deploy, so it's reachable over HTTPS at a stable hostname the same way `server` and `minio` already are.

**Architecture:** Add a `GET /health` route to `web` (no WorkOS calls) so it can get a Docker healthcheck matching `server`'s pattern. Add a third public hostname `WEB_HOSTNAME`, a Caddy site block proxying to `web:3000`, `restart: unless-stopped` in the prod overlay, and the corresponding secrets/hostname in `.env.prod.example`. Extend `docs/DEPLOY.md`'s runbook to cover the third hostname.

**Tech Stack:** Same as the base plan (Next.js 15 App Router) plus the existing Caddy/Compose prod stack.

## Global Constraints

- Never run `git commit`. Each task's final step stages changes with `git add` only — the user commits by hand.
- Use `pnpm`, never `npm`, for all package management in `web/`.
- In new TypeScript code, prefer `type` over `interface` and `??` over `||` where applicable.
- Follow the existing prod-overlay convention exactly: healthchecks and their consuming `depends_on` live in the **base** `docker-compose.yml` (used by both dev and prod); `restart: unless-stopped` lives only in `docker-compose.prod.yml`. This mirrors how `server`'s healthcheck is defined in the base file while its `restart: unless-stopped` is prod-only.
- Do not touch `SERVER_BASE_URL`/`MCP_HOSTNAME`/`S3_HOSTNAME` or any existing service's config — this plan only adds `web`'s prod wiring alongside them.

---

### Task 1: `/health` route for the web app

**Files:**
- Create: `web/app/health/route.ts`

**Interfaces:**
- Produces: `GET /health` returning HTTP 200 with JSON body `{"status":"ok"}`, matching `server`'s `/health` route exactly (see `server/dfl24sim_server/app.py:16-18`). Must not call `withAuth()`, WorkOS, or any other dependency — a healthcheck must reflect only "the Node process is up and serving," not WorkOS reachability.

- [ ] **Step 1: Create `web/app/health/route.ts`**

```ts
import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
```

- [ ] **Step 2: Build and verify the route compiles as a static/lightweight route**

Run from `web/`:
```bash
pnpm build
```
Expected: `✓ Compiled successfully`, and the route listing includes `/health` (this route has no `cookies()`/`withAuth()` call, so unlike `/` and `/callback` it may be marked static `○` rather than dynamic `ƒ` — either is fine, since it does no auth work).

- [ ] **Step 3: Smoke-test the route**

```bash
pnpm dev &
sleep 3
curl -s http://localhost:3000/health
kill %1
```
Expected output: `{"status":"ok"}`

- [ ] **Step 4: Stage (do not commit)**

```bash
git add web/app/health
```

---

### Task 2: Docker healthcheck for the `web` service

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `GET /health` from Task 1.
- Produces: the `web` service in `docker-compose.yml` reports `healthy`/`unhealthy` status, so Task 3's `caddy` `depends_on: web: condition: service_healthy` has something to wait on.

- [ ] **Step 1: Add a healthcheck to the `web` service in `docker-compose.yml`**

Find the `web` service (added by the base plan, currently looks like this):
```yaml
  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    ports:
      # loopback-only, same convention as server/postgres/minio
      - "127.0.0.1:3000:3000"
    environment:
      <<: *web-env
```

Add a `healthcheck:` block, matching `server`'s exactly in style (`server`'s healthcheck in `docker-compose.yml` uses `python -c "urllib.request.urlopen(...)"` because it's a Python image; `web`'s image has Node, so use `node`'s built-in `fetch` the same way):

```yaml
  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    ports:
      # loopback-only, same convention as server/postgres/minio
      - "127.0.0.1:3000:3000"
    environment:
      <<: *web-env
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://localhost:3000/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]
      interval: 10s
      timeout: 3s
      retries: 5
```

- [ ] **Step 2: Validate compose syntax**

```bash
docker compose config >/dev/null
```
Expected: exits 0, no error.

- [ ] **Step 3: Verify the healthcheck actually passes on a running container**

```bash
docker compose up -d --build web
sleep 12
docker compose ps web
```
Expected: the `STATUS` column shows `healthy` (not `starting` or `unhealthy`) after the containers settle. Then tear down:
```bash
docker compose down web
```

- [ ] **Step 4: Stage (do not commit)**

```bash
git add docker-compose.yml
```

---

### Task 3: Caddy site block, prod restart policy, and `depends_on`

**Files:**
- Modify: `deploy/Caddyfile`
- Modify: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: the `web` service and its healthcheck from Tasks 1-2.
- Produces: `https://$WEB_HOSTNAME` reverse-proxies to `web:3000` in production, matching how `$MCP_HOSTNAME`/`$S3_HOSTNAME` already proxy to `server`/`minio`.

- [ ] **Step 1: Add a `WEB_HOSTNAME` site block to `deploy/Caddyfile`**

Update the file's header comment and add the new block. Full new file content:

```caddyfile
# Caddy fronts the stack with automatic Let's Encrypt TLS. Three public names:
#   MCP_HOSTNAME  — the MCP endpoint (and OAuth resource metadata host)
#   S3_HOSTNAME   — the MinIO S3 API that presigned artifact URLs point at
#   WEB_HOSTNAME  — the web/ AuthKit login app
# All three are injected from the environment by the caddy service (see
# docker-compose.prod.yml). Hostnames, not ports, are what SigV4 and the OAuth
# resource URL bind to, so these must match SERVER_BASE_URL and MINIO_PUBLIC_URL.

{$MCP_HOSTNAME} {
	encode zstd gzip
	# Streamable HTTP keeps long-lived request/response streams; don't buffer
	# them, and allow ample time for a slow tool call to stream back.
	reverse_proxy server:8000 {
		flush_interval -1
		transport http {
			response_header_timeout 5m
		}
	}
}

{$S3_HOSTNAME} {
	# Serves presigned artifact downloads (GET). Uploads never traverse Caddy —
	# the worker writes straight to minio:9000 over the internal network — so no
	# request-body limit is needed here; the responses are what get large.
	reverse_proxy minio:9000
}

{$WEB_HOSTNAME} {
	encode zstd gzip
	reverse_proxy web:3000
}
```

- [ ] **Step 2: Add `restart: unless-stopped` to `web` in `docker-compose.prod.yml`**

Insert alongside the other services' identical override, after the `worker:` block's `deploy:` section and before `caddy:`:

```yaml

  web:
    restart: unless-stopped
```

- [ ] **Step 3: Add `web` to Caddy's `depends_on` in `docker-compose.prod.yml`**

Find the `caddy` service's existing `depends_on` block:
```yaml
    depends_on:
      # Caddy proxies both hosts, so wait on both backends to avoid 502s on a
      # cold start (the S3 host proxies minio).
      server:
        condition: service_healthy
      minio:
        condition: service_healthy
```
Replace with:
```yaml
    depends_on:
      # Caddy proxies all three hosts, so wait on all three backends to avoid
      # 502s on a cold start (the S3 host proxies minio).
      server:
        condition: service_healthy
      minio:
        condition: service_healthy
      web:
        condition: service_healthy
```

- [ ] **Step 4: Add `WEB_HOSTNAME` to Caddy's `environment` block in `docker-compose.prod.yml`**

Find:
```yaml
    environment:
      # DNS for both names must point at this VPS before first start, so Caddy
      # can complete the ACME challenge and provision certificates.
      MCP_HOSTNAME: ${MCP_HOSTNAME:?set MCP_HOSTNAME in .env.prod}
      S3_HOSTNAME: ${S3_HOSTNAME:?set S3_HOSTNAME in .env.prod}
```
Replace with:
```yaml
    environment:
      # DNS for all three names must point at this VPS before first start, so
      # Caddy can complete the ACME challenge and provision certificates.
      MCP_HOSTNAME: ${MCP_HOSTNAME:?set MCP_HOSTNAME in .env.prod}
      S3_HOSTNAME: ${S3_HOSTNAME:?set S3_HOSTNAME in .env.prod}
      WEB_HOSTNAME: ${WEB_HOSTNAME:?set WEB_HOSTNAME in .env.prod}
```

- [ ] **Step 5: Validate compose syntax with the prod overlay**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
```
Expected: fails with a clear `set WEB_HOSTNAME in .env.prod` style error (no `.env.prod` exists yet in this checkout — that's correct/expected, it proves the `:?` guard works). Confirm the error message names exactly `WEB_HOSTNAME`, not a YAML syntax error. If you want a clean non-erroring validation, additionally run:
```bash
WEB_HOSTNAME=web.example.com MCP_HOSTNAME=mcp.example.com S3_HOSTNAME=s3.example.com \
POSTGRES_PASSWORD=x MINIO_ROOT_PASSWORD=x \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
```
Expected: exits 0.

- [ ] **Step 6: Stage (do not commit)**

```bash
git add deploy/Caddyfile docker-compose.prod.yml
```

---

### Task 4: `.env.prod.example` and `docs/DEPLOY.md`

**Files:**
- Modify: `.env.prod.example`
- Modify: `docs/DEPLOY.md`

**Interfaces:**
- Consumes: `WEB_HOSTNAME` from Task 3, `WORKOS_CLIENT_ID`/`WORKOS_API_KEY`/`WORKOS_COOKIE_PASSWORD`/`WEB_REDIRECT_URI` from the base plan's `x-web-env` anchor in `docker-compose.yml`.
- Produces: a complete, documented set of prod secrets/hostnames for `web`, and a runbook that mentions the third hostname end to end.

- [ ] **Step 1: Add `WEB_HOSTNAME` to `.env.prod.example`'s hostnames section**

Find:
```
# --- Public hostnames (Caddy TLS) -------------------------------------------
# DNS A/AAAA records for both must point at this VPS before first `up`.
MCP_HOSTNAME=mcp.example.com
S3_HOSTNAME=artifacts.example.com
# The MCP endpoint's public URL; OAuth resource metadata is published here.
SERVER_BASE_URL=https://mcp.example.com
```
Replace with:
```
# --- Public hostnames (Caddy TLS) -------------------------------------------
# DNS A/AAAA records for all three must point at this VPS before first `up`.
MCP_HOSTNAME=mcp.example.com
S3_HOSTNAME=artifacts.example.com
WEB_HOSTNAME=web.example.com
# The MCP endpoint's public URL; OAuth resource metadata is published here.
SERVER_BASE_URL=https://mcp.example.com
```

- [ ] **Step 2: Add the `web` app's WorkOS section to `.env.prod.example`**

Find:
```
# --- WorkOS AuthKit (production OAuth) --------------------------------------
# Empty disables auth — never leave empty in production.
AUTHKIT_DOMAIN=https://your-app.authkit.app
```
Replace with:
```
# --- WorkOS AuthKit (production OAuth) --------------------------------------
# Empty disables auth — never leave empty in production.
AUTHKIT_DOMAIN=https://your-app.authkit.app

# --- WorkOS AuthKit hosted login for web/ -----------------------------------
# Same AuthKit project as AUTHKIT_DOMAIN above — see web/README.md.
WORKOS_CLIENT_ID=client_CHANGE_ME
WORKOS_API_KEY=sk_live_CHANGE_ME
WORKOS_COOKIE_PASSWORD=CHANGE_ME_long_random_secret
WEB_REDIRECT_URI=https://web.example.com/callback
```

- [ ] **Step 3: Update `docs/DEPLOY.md`'s architecture diagram**

Find the diagram block:
```
            https://mcp.example.com          https://artifacts.example.com
                      │                                   │
                 ┌────▼─────────────────── Caddy ─────────▼────┐
                 │            (TLS, reverse proxy)             │
                 └────┬───────────────────────────────┬───────┘
                      │ server:8000                    │ minio:9000
                 ┌────▼────┐   ┌────────┐   ┌──────────▼──┐   ┌───────────┐
                 │ server  │   │ worker │   │    minio    │   │ postgres  │
                 └────┬────┘   └───┬────┘   └─────────────┘   └───────────┘
                      └── jobs ────┴──────────► (queue + store)
```
Replace with:
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

- [ ] **Step 4: Update the DNS one-time-setup step**

Find:
```
2. **DNS** — point both hostnames at the VPS (A/AAAA):
   - `MCP_HOSTNAME` → the MCP endpoint (e.g. `mcp.example.com`)
   - `S3_HOSTNAME` → the artifact endpoint (e.g. `artifacts.example.com`)
   Caddy provisions certificates on first start via the ACME HTTP challenge,
   so DNS must resolve *before* `up`.
```
Replace with:
```
2. **DNS** — point all three hostnames at the VPS (A/AAAA):
   - `MCP_HOSTNAME` → the MCP endpoint (e.g. `mcp.example.com`)
   - `S3_HOSTNAME` → the artifact endpoint (e.g. `artifacts.example.com`)
   - `WEB_HOSTNAME` → the AuthKit login app (e.g. `web.example.com`)
   Caddy provisions certificates on first start via the ACME HTTP challenge,
   so DNS must resolve *before* `up`.
```

- [ ] **Step 5: Update the WorkOS one-time-setup step**

Find:
```
3. **WorkOS** — create a production AuthKit environment, enable Dynamic Client
   Registration, and add `https://<MCP_HOSTNAME>/oauth2/callback` as a
   redirect (see `server/dfl24sim_server/auth.py`).
```
Replace with:
```
3. **WorkOS** — create a production AuthKit environment, enable Dynamic Client
   Registration, and add `https://<MCP_HOSTNAME>/oauth2/callback` as a
   redirect (see `server/dfl24sim_server/auth.py`). Also add
   `https://<WEB_HOSTNAME>/callback` as a redirect for the `web/` app's hosted
   login (see `web/README.md`) — same WorkOS project, different SDK/flow.
```

- [ ] **Step 6: Update the secrets one-time-setup step**

Find:
```
4. **Secrets** — `cp .env.prod.example .env.prod`, then fill in real values:
   long random `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD`, the two hostnames,
   `SERVER_BASE_URL=https://<MCP_HOSTNAME>`,
   `MINIO_PUBLIC_URL=https://<S3_HOSTNAME>`, and `AUTHKIT_DOMAIN`. Set
   `WORKER_CPUS` to about (cores − 1) so a running study leaves the API and
   Postgres a core. `chmod 600 .env.prod`.
```
Replace with:
```
4. **Secrets** — `cp .env.prod.example .env.prod`, then fill in real values:
   long random `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD`, all three
   hostnames, `SERVER_BASE_URL=https://<MCP_HOSTNAME>`,
   `MINIO_PUBLIC_URL=https://<S3_HOSTNAME>`, `AUTHKIT_DOMAIN`, and the web
   app's `WORKOS_CLIENT_ID` / `WORKOS_API_KEY` / `WORKOS_COOKIE_PASSWORD` /
   `WEB_REDIRECT_URI=https://<WEB_HOSTNAME>/callback`. Set `WORKER_CPUS` to
   about (cores − 1) so a running study leaves the API and Postgres a core.
   `chmod 600 .env.prod`.
```

- [ ] **Step 7: Stage (do not commit)**

```bash
git add .env.prod.example docs/DEPLOY.md
```

---

## Self-Review Notes

- **Spec coverage:** `/health` route (Task 1), Docker healthcheck (Task 2), Caddy site block + prod restart + depends_on (Task 3), `.env.prod.example` + `DEPLOY.md` runbook (Task 4) — all four pieces the user asked for ("add WEB_HOSTNAME + a Caddy site block + TLS + the WORKOS_* vars in .env.prod.example") are covered; TLS itself needs no new code since Caddy's existing ACME config already covers any hostname it's given a site block for.
- **Placeholder scan:** no TBD/TODO. Task 3 Step 5's expected-failure validation is intentional (proves the `:?` guard works with no `.env.prod` present in this checkout) and gives the follow-up all-vars-set command for a clean check.
- **Type consistency:** `WEB_HOSTNAME` used identically across `deploy/Caddyfile`, `docker-compose.prod.yml`, and `.env.prod.example`; `/health` route name and response shape match `server`'s `/health` exactly, so `docs/DEPLOY.md`'s existing smoke-test pattern (`curl -fsS https://$MCP_HOSTNAME/health`) generalizes to `web` without further changes needed there.
