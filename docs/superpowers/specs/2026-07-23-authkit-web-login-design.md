# AuthKit Web Login — Design

## Purpose

DFL24-Sim currently has no web frontend: users interact only through the MCP
connector (Claude/ChatGPT), where WorkOS AuthKit already handles OAuth 2.1 for
tool calls (`server/dfl24sim_server/auth.py`). This adds a minimal standalone
Next.js app whose only job is a working WorkOS AuthKit hosted login: sign in,
show who you are (email + org id), sign out. It is a foundation to build a
real dashboard/console on later — not that dashboard itself.

**Non-goals:** no job/results UI, no org admin/invite UI, no protected-route
middleware, no production (VPS/Caddy) deployment wiring. All explicitly
deferred to follow-up work once this app does more than show login state.

## Assumption

The WorkOS Client ID / API key this app uses come from the same WorkOS
AuthKit-enabled project as the existing `AUTHKIT_DOMAIN` used by the MCP
server — a different SDK/flow (hosted AuthKit login via
`@workos-inc/authkit-nextjs`) against the same WorkOS environment, not a
second WorkOS project. The operator must add the app's redirect URI
(`http://localhost:3000/callback` in dev) as an allowed Redirect URI in that
same WorkOS dashboard.

## Architecture

New `web/` directory: Next.js 15 (App Router), TypeScript, pnpm, using
`@workos-inc/authkit-nextjs` + `@workos-inc/node`.

- `web/app/layout.tsx` — server component; calls `withAuth()`, strips
  `accessToken`, passes the rest as `initialAuth` to `AuthKitProvider`
  wrapping `children` (avoids a redundant client-side auth fetch on mount).
- `web/app/page.tsx` — server component; calls `withAuth()` again for the
  page's own render:
  - no user → renders a "Sign in" link built from `getSignInUrl()`
  - user present → renders "Signed in as `{email}`" + `organizationId`, plus
    a sign-out `<form>` whose server action calls `signOut()`
- `web/app/callback/route.ts` — `export const GET = handleAuth()`. Path must
  match `NEXT_PUBLIC_WORKOS_REDIRECT_URI`.
- No `middleware.ts` — nothing is force-protected. The homepage simply
  reflects whatever auth state exists; this keeps the app a pure login
  foundation rather than a gated app.
- `web/.env.local.example` documents the four required vars:
  `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_COOKIE_PASSWORD`,
  `NEXT_PUBLIC_WORKOS_REDIRECT_URI`.

## Docker / compose integration

- `web/Dockerfile` — Node 24-slim, multi-stage (`pnpm install
  --frozen-lockfile` → `pnpm build` → `next start` on port 3000), built from
  the repo root the same way `server/Dockerfile` is (`docker build -f
  web/Dockerfile .`).
- `docker-compose.yml` gains a `web` service:
  - env anchor `x-web-env` carrying `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`,
    `WORKOS_COOKIE_PASSWORD`, `NEXT_PUBLIC_WORKOS_REDIRECT_URI` (defaulted
    from `WEB_REDIRECT_URI`, itself defaulting to
    `http://localhost:3000/callback`)
  - published loopback-only, `127.0.0.1:3000:3000`, matching the existing
    `server`/`postgres`/`minio` convention
  - no `depends_on` — this app doesn't touch Postgres/MinIO, only WorkOS
- `.env.example` gains the corresponding `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`,
  `WORKOS_COOKIE_PASSWORD`, `WEB_REDIRECT_URI` entries (blank/placeholder,
  same style as the existing `AUTHKIT_DOMAIN=` line), with a comment pointing
  at `web/README.md` for how to obtain them from the WorkOS dashboard.
- Explicitly out of scope: `docker-compose.prod.yml`, `deploy/Caddyfile` — no
  public hostname/TLS wiring for this app yet.

## Verification plan

1. `pnpm install` in `web/`, `pnpm dev`.
2. With real WorkOS AuthKit dev credentials in `web/.env.local`: click
   sign-in → complete AuthKit hosted login → redirected to `/callback` →
   homepage shows email + org id → sign-out clears the session and the page
   reverts to the sign-in link.
3. `docker compose up web` builds the image and serves the same flow on port
   3000.
4. Without any WorkOS credentials configured, `pnpm build` still succeeds
   (no build-time calls to WorkOS) — confirms the app is safe to include in
   `docker compose up` even before an operator has WorkOS creds on hand;
   hitting the sign-in link at runtime will fail loudly instead.
