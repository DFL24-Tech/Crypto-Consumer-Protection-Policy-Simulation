# Connect DFL24-Sim to ChatGPT (Developer Mode)

DFL24-Sim is a standard [MCP](https://modelcontextprotocol.io) server, so
ChatGPT can use it too — through **Developer Mode**, which lets you add an MCP
server as a custom connector. This is the **secondary** path; the
[Claude connector](CONNECT-CLAUDE.md) is the primary, better-supported one.

> Use the real hostname from your operator in place of `mcp.example.com` — for
> this deployment that's `sim-api.dfl24.com`. The connector URL is that
> hostname with `/mcp`: **`https://sim-api.dfl24.com/mcp`**

## Read this first — what to expect

- **Developer Mode is required.** MCP connectors live behind it; a plain ChatGPT
  account can't add one until Developer Mode is enabled. Availability and exact
  menu names vary by plan and change over time — if a label here doesn't match,
  look for the nearest equivalent under Settings → Connectors.
- **It's a tool connector, not an app.** ChatGPT calls the same tools Claude
  does, but there is **no first-class app experience**: no custom UI, no rich
  cards — just tool calls and text.
- **Plugins are gone; the Apps SDK path is deferred.** ChatGPT plugins no longer
  exist, so there is no plugin manifest to install. A richer integration via the
  ChatGPT **Apps SDK** is possible in principle but is **explicitly out of scope
  here** — this guide covers the MCP-connector path only.
- **Auth caveat.** DFL24-Sim requires an OAuth login (WorkOS AuthKit) and scopes
  jobs to your organization. MCP connector OAuth support in ChatGPT Developer
  Mode is newer and less battle-tested than Claude's; if the login handshake
  fails, prefer the Claude path and file the specifics with your operator.

## Enable Developer Mode

1. In ChatGPT, open **Settings → Connectors** (web or desktop app).
2. Find **Advanced** / **Developer Mode** and turn it on. If you don't see it,
   your plan or workspace may not expose custom MCP connectors yet — stop here
   and use the [Claude connector](CONNECT-CLAUDE.md).

## Add the connector

1. Under **Connectors**, choose **Create** / **Add custom connector** (the
   Developer-Mode entry point).
2. Name it `DFL24-Sim` and paste the MCP URL: `https://sim-api.dfl24.com/mcp`.
3. Save. When prompted, **Connect** and complete the AuthKit login with your
   organization account.
4. In a new chat, enable the DFL24-Sim connector for that conversation (the
   tools/Developer-Mode menu), then confirm the tools are listed.

## Verify it works

Run the same worked example as the Claude guide — the tools and behavior are
identical:

1. **Cite:** "In DFL24-Sim, how bad is the coverage gap once adversaries adapt?"
   → `get_reference_results` (instant).
2. **Simulate:** "Run the pig-butchering scenario across 4 seeds." →
   `run_scenario` (seconds).
3. **Study:** "Kick off the full policy × attack study," then ask it to check
   status and, once done, fetch the result and the battery figure →
   `run_study` → `get_job_status` → `get_job_result` → `get_artifact`.

See [the Claude worked example](CONNECT-CLAUDE.md#a-worked-example) for the full
narration and what each step should return. The same guardrails apply: results
are simulation output not field measurements, heavy work runs as background
jobs, and your organization is capped at 2 concurrent jobs.

## Troubleshooting

- **No Developer Mode / no "add connector"** — not available on your plan or
  workspace. Use the [Claude connector](CONNECT-CLAUDE.md).
- **Connector added but login fails** — this is the least-tested path; verify
  `https://<your-host>/health` returns `{"status":"ok"}`, then fall back to
  Claude and report the failure to your operator.
- **Tools error with "no organization" / "at its job quota"** — same meanings as
  in the [Claude guide's troubleshooting](CONNECT-CLAUDE.md#troubleshooting);
  they come from the server, not the client.

---

Primary path: [Connect via Claude](CONNECT-CLAUDE.md).
Operators: [production deployment & runbook](DEPLOY.md).
