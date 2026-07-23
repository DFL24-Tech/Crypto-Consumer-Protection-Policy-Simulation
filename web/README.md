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
