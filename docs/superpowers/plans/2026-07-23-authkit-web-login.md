# AuthKit Web Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `web/` Next.js app that lets a user sign in via WorkOS AuthKit hosted login, see who they are, and sign out — a foundation for a real dashboard later, not that dashboard.

**Architecture:** Next.js 15 App Router app using `@workos-inc/authkit-nextjs` for the hosted AuthKit login flow (sign-in link → WorkOS-hosted login → `/callback` → session cookie). No middleware, no protected routes — the homepage just reflects whatever auth state exists. Wired into `docker-compose.yml` as a `web` service alongside the existing `server`/`postgres`/`minio` services, built from a new `web/Dockerfile`.

**Tech Stack:** Next.js 15, React 19, TypeScript, pnpm, `@workos-inc/authkit-nextjs` + `@workos-inc/node`, Node 24-slim (Docker).

## Global Constraints

- Never run `git commit`. Each task's final step stages changes with `git add` only — the user commits by hand (user's global CLAUDE.md).
- Use `pnpm`, never `npm`, for all package management in `web/` (user's global preference).
- In new TypeScript code, prefer `type` over `interface` and `??` over `||` where applicable (user's global preference).
- No `middleware.ts` / force-protected routes in this app (design non-goal).
- No changes to `docker-compose.prod.yml` or `deploy/Caddyfile` (design non-goal — production wiring is a later follow-up).
- The WorkOS Client ID / API key this app uses come from the same WorkOS AuthKit project as the existing `AUTHKIT_DOMAIN` used by `server/dfl24sim_server/auth.py` (design assumption) — real credentials are supplied by the user later in `web/.env.local`, not part of this plan.

---

### Task 1: Scaffold the Next.js app

**Files:**
- Create: `web/package.json`
- Create: `web/.gitignore`
- Create: `web/app/layout.tsx`
- Create: `web/app/page.tsx`
- Create: `web/public/.gitkeep`

**Interfaces:**
- Produces: a `web/` directory that builds with `pnpm build` and serves with `pnpm dev`; `web/app/layout.tsx` exports default `RootLayout({ children }: { children: ReactNode })`; `web/app/page.tsx` exports default `HomePage()`. Task 2 replaces the bodies of both.

- [x] **Step 1: Create `web/.gitignore`**

```
# dependencies
node_modules/

# next.js build output
.next/
out/

# local env files (never commit real credentials)
.env*.local

# misc
.DS_Store
*.pem
tsconfig.tsbuildinfo
```

- [x] **Step 2: Create `web/package.json`**

```json
{
  "name": "dfl24sim-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }
}
```

- [x] **Step 3: Install Next.js and React**

Run from `web/`:
```bash
cd web && pnpm add next react react-dom
```
Expected: `web/package.json` gains a `dependencies` block for `next`, `react`, `react-dom`; `web/pnpm-lock.yaml` is created.

- [x] **Step 4: Install TypeScript dev dependencies**

Run from `web/`:
```bash
pnpm add -D typescript @types/node @types/react @types/react-dom
```
Expected: `web/package.json` gains a `devDependencies` block for all four packages.

- [x] **Step 5: Create `web/app/layout.tsx` (placeholder — Task 2 wires AuthKit in)**

```tsx
import type { ReactNode } from "react";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

- [x] **Step 6: Create `web/app/page.tsx` (placeholder — Task 2 wires AuthKit in)**

```tsx
export default function HomePage() {
  return <p>DFL24-Sim web — scaffold OK.</p>;
}
```

- [x] **Step 7: Create empty `web/public/.gitkeep`**

Empty file — keeps the `public/` directory present for Task 3's Dockerfile `COPY`, since Next.js doesn't require any files in it for this app.

- [x] **Step 8: Build to verify the scaffold and auto-generate `tsconfig.json`**

Run:
```bash
pnpm build
```
Expected: `✓ Compiled successfully`, and Next.js auto-creates `web/tsconfig.json` and `web/next-env.d.ts` (it does this automatically the first time it finds `.tsx` files with `typescript` installed but no `tsconfig.json`).

- [x] **Step 9: Smoke-test the dev server**

Run in the background, then check it, then stop it:
```bash
pnpm dev &
sleep 3
curl -s http://localhost:3000 | grep "scaffold OK"
kill %1
```
Expected: the `grep` prints the matching line (page rendered).

- [x] **Step 10: Stage (do not commit)**

```bash
git add web/package.json web/pnpm-lock.yaml web/.gitignore web/app web/public web/tsconfig.json web/next-env.d.ts
```

---

### Task 2: Wire AuthKit into layout, homepage, and callback route

**Files:**
- Modify: `web/package.json` (via `pnpm add`)
- Create: `web/.env.local.example`
- Modify: `web/app/layout.tsx`
- Modify: `web/app/page.tsx`
- Create: `web/app/callback/route.ts`

**Interfaces:**
- Consumes: `RootLayout`/`HomePage` scaffolds from Task 1.
- Produces: the actual login flow. `web/app/callback/route.ts` exports `GET`, the route WorkOS redirects to; its path (`/callback`) must match `NEXT_PUBLIC_WORKOS_REDIRECT_URI`.

- [x] **Step 1: Install AuthKit packages**

Run from `web/`:
```bash
pnpm add @workos-inc/authkit-nextjs @workos-inc/node
```
Expected: both added to `dependencies`.

- [x] **Step 2: Create `web/.env.local.example`**

```
# Get these from the WorkOS dashboard — see web/README.md for the exact
# steps. This uses the same AuthKit project as AUTHKIT_DOMAIN in the repo
# root .env (see server/dfl24sim_server/auth.py).
WORKOS_CLIENT_ID=
WORKOS_API_KEY=
# Generate with: openssl rand -base64 24
WORKOS_COOKIE_PASSWORD=
NEXT_PUBLIC_WORKOS_REDIRECT_URI=http://localhost:3000/callback
```

- [x] **Step 3: Replace `web/app/layout.tsx`**

```tsx
import type { ReactNode } from "react";
import { AuthKitProvider } from "@workos-inc/authkit-nextjs/components";
import { withAuth } from "@workos-inc/authkit-nextjs";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const { accessToken, ...initialAuth } = await withAuth();

  return (
    <html lang="en">
      <body>
        <AuthKitProvider initialAuth={initialAuth}>{children}</AuthKitProvider>
      </body>
    </html>
  );
}
```

- [x] **Step 4: Replace `web/app/page.tsx`**

```tsx
import { getSignInUrl, signOut, withAuth } from "@workos-inc/authkit-nextjs";

export default async function HomePage() {
  const { user, organizationId } = await withAuth();

  if (!user) {
    const signInUrl = await getSignInUrl();
    return (
      <main>
        <a href={signInUrl}>Sign in</a>
      </main>
    );
  }

  return (
    <main>
      <p>
        Signed in as {user.email}
        {organizationId ? ` (org ${organizationId})` : ""}
      </p>
      <form
        action={async () => {
          "use server";
          await signOut();
        }}
      >
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
```

> **Note (superseded during final review, see progress ledger):** the plan
> above was the original design, but calling `getSignInUrl()` directly in a
> Server Component's render body turned out to be broken on Next.js 15 —
> `getSignInUrl()` sets a PKCE cookie internally, and Next.js only allows
> cookie mutation inside a Server Action or Route Handler. The as-built code
> instead moves sign-in URL generation into `web/app/sign-in/route.ts` (a
> Route Handler) and has `page.tsx` link to `/sign-in` — see that file and
> `web/middleware.ts` for the as-built, verified-working version.

- [x] **Step 5: Create `web/app/callback/route.ts`**

```ts
import { handleAuth } from "@workos-inc/authkit-nextjs";

export const GET = handleAuth();
```

- [x] **Step 6: Build without any WorkOS credentials set, to confirm the app doesn't require them at build time**

Run from `web/` (ensure no `.env.local` exists yet, or that it's empty):
```bash
pnpm build
```
Expected: `✓ Compiled successfully`. `withAuth()` reads cookies, which forces the routes using it to render dynamically (per-request) rather than being statically evaluated at build time — so no WorkOS API call happens during `pnpm build`.

- [x] **Step 7: Record manual verification to run later, once real credentials exist**

This step can't be automated now — no WorkOS credentials are available yet. Leave this note for whoever adds `web/.env.local`:
1. Copy `web/.env.local.example` to `web/.env.local` and fill in real values (see `web/README.md`, written in Task 5).
2. `pnpm dev`, open `http://localhost:3000`.
3. Click "Sign in" → complete AuthKit hosted login → confirm redirect back to `http://localhost:3000/callback` → confirm the homepage now shows "Signed in as `<email>`" and, if the account belongs to an org, `(org <id>)`.
4. Click "Sign out" → confirm the homepage reverts to showing the "Sign in" link.

- [x] **Step 8: Stage (do not commit)**

```bash
git add web/package.json web/pnpm-lock.yaml web/.env.local.example web/app
```

---

### Task 3: Dockerfile for the web app

**Files:**
- Create: `web/Dockerfile`

**Interfaces:**
- Consumes: `web/package.json` + `web/pnpm-lock.yaml` from Task 1, the `web/app` tree from Task 2, `web/public/` from Task 1.
- Produces: an image that runs `pnpm start` on port 3000, built the same way `server/Dockerfile` is: `docker build -f web/Dockerfile .` from the repo root.

- [x] **Step 1: Create `web/Dockerfile`**

```dockerfile
# Build from the repository root: docker build -f web/Dockerfile .
FROM node:24-slim AS base
RUN corepack enable && corepack prepare pnpm@10 --activate

FROM base AS deps
WORKDIR /app
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ .
RUN pnpm build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000
CMD ["pnpm", "start"]
```

> **Note (superseded during final review):** the as-built Dockerfile adds an
> `ARG`/`ENV NEXT_PUBLIC_WORKOS_REDIRECT_URI` before `RUN pnpm build` in the
> `builder` stage — `NEXT_PUBLIC_*` vars are inlined into the JS bundle at
> Next.js build time, not read at runtime, so this must be a build arg, not
> a runtime `environment:` var. See the current `web/Dockerfile`.

- [x] **Step 2: Build the image**

Run from the repo root:
```bash
docker build -f web/Dockerfile -t dfl24sim-web .
```
Expected: build succeeds (this exercises the same no-credentials `pnpm build` path verified in Task 2 Step 6, since no `WORKOS_*` build args/env are passed).

- [x] **Step 3: Smoke-test the container starts and serves**

```bash
docker run --rm -d -p 3000:3000 --name dfl24sim-web-smoke dfl24sim-web
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000
docker stop dfl24sim-web-smoke
```
Expected: the container starts without crashing. The HTTP status may be a 500 (not 200) since no `WORKOS_*` env vars are set for this standalone smoke test and rendering the sign-in link calls into the AuthKit SDK — that's expected and matches the design's documented limitation ("hitting the sign-in link will fail loudly instead" without credentials). What this step actually confirms is that the image builds and the process starts and responds, not a full login flow.

- [x] **Step 4: Stage (do not commit)**

```bash
git add web/Dockerfile
```

---

### Task 4: Wire `web` into docker-compose.yml and .env.example

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `web/Dockerfile` from Task 3.
- Produces: `docker compose up web` builds and runs the app on `127.0.0.1:3000`.

- [x] **Step 1: Add a `x-web-env` anchor to `docker-compose.yml`**

Insert immediately after the existing `x-s3-env` block (after its final line `DFL24_S3_SECRET_KEY: ${MINIO_ROOT_PASSWORD:-dfl24secret}`, before `services:`):

```yaml

x-web-env: &web-env
  WORKOS_CLIENT_ID: ${WORKOS_CLIENT_ID:-}
  WORKOS_API_KEY: ${WORKOS_API_KEY:-}
  WORKOS_COOKIE_PASSWORD: ${WORKOS_COOKIE_PASSWORD:-}
  NEXT_PUBLIC_WORKOS_REDIRECT_URI: ${WEB_REDIRECT_URI:-http://localhost:3000/callback}
```

- [x] **Step 2: Add the `web` service to `docker-compose.yml`**

Insert a new service after the `server:` service block (after its `healthcheck:` block ends, before `worker:` begins):

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

- [x] **Step 3: Add WorkOS vars to `.env.example`**

Append after the existing `SERVER_BASE_URL=http://localhost:8000` line:

```
# WorkOS AuthKit hosted login for the web/ app (same AuthKit project as
# AUTHKIT_DOMAIN above — see web/README.md for setup steps)
WORKOS_CLIENT_ID=
WORKOS_API_KEY=
WORKOS_COOKIE_PASSWORD=
WEB_REDIRECT_URI=http://localhost:3000/callback
```

- [x] **Step 4: Validate compose syntax**

```bash
docker compose config >/dev/null
```
Expected: exits 0 with no error (confirms the YAML and anchor references are valid — this does not start any services).

- [x] **Step 5: Stage (do not commit)**

```bash
git add docker-compose.yml .env.example
```

---

### Task 5: `web/README.md` setup instructions

**Files:**
- Create: `web/README.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: the doc referenced from `web/.env.local.example` and `.env.example`.

- [x] **Step 1: Create `web/README.md`**

```markdown
# DFL24-Sim web

A minimal Next.js app whose only job is a working WorkOS AuthKit hosted
login: sign in, see who you are, sign out. It's a foundation for a real
dashboard later, not that dashboard.

## Get WorkOS credentials

This app uses the **same WorkOS AuthKit project** as the MCP server's
`AUTHKIT_DOMAIN` (see `server/dfl24sim_server/auth.py`) — just a different
SDK/flow (hosted AuthKit login here, vs. the MCP OAuth resource-server flow
there).

1. Sign in to the [WorkOS dashboard](https://dashboard.workos.com).
2. Open the same environment/project used for the MCP server's AuthKit
   domain.
3. Under **API Keys**, copy the **Client ID** and **Secret Key** — these
   become `WORKOS_CLIENT_ID` and `WORKOS_API_KEY`.
4. Under **Redirects**, add `http://localhost:3000/callback` as an allowed
   redirect URI for local development (add your production URL's
   `/callback` too once this app is deployed).
5. Generate a cookie-encryption password: `openssl rand -base64 24`. This
   becomes `WORKOS_COOKIE_PASSWORD`.

## Run locally

```bash
cp .env.local.example .env.local
# fill in the four values from above
pnpm install
pnpm dev
```

Open `http://localhost:3000`, click **Sign in**, complete the WorkOS-hosted
login, and confirm you land back on the homepage signed in.

## Run via Docker Compose

From the repo root, with the same four `WORKOS_*` values (plus optionally
`WEB_REDIRECT_URI`) set in your root `.env`:

```bash
docker compose up web
```
```

- [x] **Step 2: Stage (do not commit)**

```bash
git add web/README.md
```

---

## Self-Review Notes

- **Spec coverage:** architecture (Tasks 1–2), Docker/compose integration (Tasks 3–4), env vars (Tasks 2, 4), WorkOS-project assumption documented for the operator (Task 5), all four verification-plan steps from the spec covered (Task 1 Step 9 dev smoke test; Task 2 Steps 6–7 no-creds build + manual flow note; Task 3 Step 2 compose/Docker build).
- **Placeholder scan:** no TBD/TODO; the one deliberately-deferred item (Task 2 Step 7, the real login click-through) is explicit about *why* it can't run now (no credentials exist yet) and gives the exact steps to run it later, not a vague "add tests."
- **Type consistency:** `organizationId` and `user` are read from `withAuth()` in both `layout.tsx` and `page.tsx` with the same shape; `getSignInUrl`, `signOut`, `withAuth`, `handleAuth`, `AuthKitProvider` names match the installed package's documented API used consistently across Tasks 2–3.

## Post-implementation note

All 5 tasks were implemented and individually reviewed clean. A subsequent
final-review round (after this plan's Phase 2/3 follow-ups were also
implemented) found that the login flow as originally planned above didn't
actually work at runtime on Next.js 15 — see the inline notes on Task 2 Step
4 and Task 3 Step 1 above for what changed, and the branch's progress
ledger (`.superpowers/sdd/progress.md`) for the full fix history:
`web/middleware.ts` was added (required by `@workos-inc/authkit-nextjs` on
Next.js ≤15), sign-in URL generation moved to `web/app/sign-in/route.ts`,
the middleware matcher was widened to cover all page routes, and
`NEXT_PUBLIC_WORKOS_REDIRECT_URI` was moved from a runtime `environment:`
var to a Docker build `ARG`. All fixes were verified against the actual
built Docker image with real HTTP requests, not just `pnpm build`.
