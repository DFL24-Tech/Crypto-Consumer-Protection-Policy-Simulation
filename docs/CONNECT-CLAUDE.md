# Connect DFL24-Sim to Claude

This guide adds DFL24-Sim to Claude as a **custom connector**, so you can ask a
policy question in plain language and Claude runs the simulator for you. No
coding — if you can use claude.ai, you can follow this.

> Wherever this guide says `mcp.example.com`, use the real hostname your
> operator gave you — for this deployment that's `sim-api.dfl24.com`. The
> connector URL is that hostname with `/mcp` on the end:
> **`https://sim-api.dfl24.com/mcp`**

## Before you start

- A Claude account on a plan that supports custom connectors (Pro, Max, Team,
  or Enterprise). On Team/Enterprise an admin may need to allow custom
  connectors for the workspace.
- The connector URL from your operator (`https://<your-host>/mcp`).
- That you belong to an **organization** in the login system — DFL24-Sim scopes
  every job to your org, so you only ever see your own runs.

## Add the connector

1. In claude.ai, open **Settings → Connectors** (also called "Connectors" in
   the sidebar of a new chat).
2. Click **Add custom connector**.
3. Give it a name (e.g. `DFL24-Sim`) and paste the URL:
   `https://sim-api.dfl24.com/mcp`
4. Click **Add**, then **Connect**. Claude opens a login window (WorkOS
   AuthKit). Sign in with your organization account and approve access.
5. The connector shows as **Connected**. Open a new chat and confirm the
   DFL24-Sim tools appear in the connector/tools menu (the 🔌 or tools icon).

If the login window doesn't appear or returns an error, see
[Troubleshooting](#troubleshooting).

## What you can ask it to do

You don't call tools by name — you ask in plain language and Claude picks the
right one. The connector exposes three kinds of capability:

| You want to… | Ask something like… | Speed |
|---|---|---|
| **Cite a paper number** | "What's the adaptive coverage gap in DFL24-Sim?" | instant (precomputed) |
| **Run a quick simulation** | "Run the pig-butchering scenario across 4 seeds." | seconds |
| **Run a heavy study** | "Kick off the full policy × attack study." | minutes (background job) |

Heavy work (`run_study`, `run_calibration`, `run_gsa`, `run_sweep`) runs as a
**background job**: Claude gets a job id immediately, and you ask it to check
status and fetch the result when it's done. Your organization can have up to
**2 jobs running at once**, and asking the same question twice returns the
cached result instead of re-running.

> **Every number is a simulation result, not a field measurement.** The tools
> say so, and Claude will repeat it — treat the output as evidence from a
> calibrated model, not from the field.

## A worked example

Follow this conversation to exercise all three capability classes end to end.

**1 — Look up a headline number (instant, no compute).**

> **You:** In DFL24-Sim, how bad is the coverage gap once adversaries adapt?

Claude calls `get_reference_results` and reports the precomputed figures: static
rule-based detection of 50–100% collapsing to roughly **9–19%** once adversaries
adapt, with the cyber class never caught — each with its white-paper section and
the simulation-not-field caveat.

**2 — Run a scenario yourself (seconds).**

> **You:** Run the pig-butchering scenario across 4 seeds and tell me whether
> friction actually helps the victims.

Claude calls `run_scenario` (name `C1_pig_butchering_wave`) and returns
across-seed means with Monte-Carlo error, including the victim take-rate with
versus without the friction prompt. Ask it to interpret the gap.

**3 — Trigger a heavy study (minutes, background).**

> **You:** Now kick off the full policy × attack study.

Claude calls `run_study` and returns a **job id** with status `queued`.

> **You:** Is it done yet?

Claude calls `get_job_status`. Repeat until it reports `done` (a small study is
a minute or two).

> **You:** Great — pull the results and the battery figure.

Claude calls `get_job_result` (the 4 policy regimes × 5 attack worlds, with
coverage, retail burn, trust, and precision per cell) and `get_artifact` to
return a time-limited link to `fig_battery.png`. Ask it which policy is
dominated — it should point at *over-friction* (matches standard on coverage,
destroys trust).

That's the full loop: **cite → simulate → study → fetch**.

## Tips for good answers

- **Name the scenario or ask for the list.** "List the scenarios" calls
  `list_scenarios`; the twelve names (e.g. `A3_crash_cascade`,
  `B4_adaptive_red_team`, `D2_over_friction_fatigue`) each answer a specific
  question.
- **Keep sizes reasonable.** The tools cap per request (≤100k agents, ≤60
  steps, ≤8 seeds); Claude will stay within them.
- **Let jobs run.** After triggering a study, do something else and come back —
  ask "check my recent jobs" (a bare `get_job_status`) to see everything your
  org has running.
- **Re-runs are cheap.** The same parameters return the cached result. To force
  a fresh run, say "re-run it even if cached".

## Troubleshooting

- **No login window / "connection failed" when connecting** — the URL must end
  in `/mcp` and be reachable over HTTPS. Open `https://<your-host>/health` in a
  browser; it should return `{"status":"ok"}`. If not, contact your operator.
- **Login succeeds but tools error with "no organization"** — your account
  isn't attached to an organization in AuthKit. Ask your operator to add you to
  one; jobs are org-scoped and require it.
- **"at its job quota"** — your organization already has 2 jobs queued or
  running. Ask Claude to check their status and wait for one to finish, or fetch
  a result you already have.
- **A job is stuck in `running` far too long** — tell your operator the job id;
  the [deploy runbook](DEPLOY.md#re-run-a-stuck-job) covers resetting it.
- **You can't see a colleague's job** — that's by design. Jobs are visible only
  within the organization that created them.

---

Secondary path: [Connect via ChatGPT Developer Mode](CONNECT-CHATGPT.md).
Operators: [production deployment & runbook](DEPLOY.md).
