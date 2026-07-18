"""The DFL24-Sim MCP server: tools a policy analyst's LLM can call."""
import math
import uuid
from dataclasses import replace

import psycopg
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from dfl24sim import SimConfig, run, scenarios, sweeps

from . import db, jobs, reference, storage
from .auth import caller_org

mcp = FastMCP("DFL24-Sim")

# Hard per-request caps: tool calls run synchronously inside a chat turn, so a
# request must stay in the seconds range on one worker.
MAX_AGENTS = 100_000
MAX_STEPS = 60
MAX_SEEDS = 8
# Background-job caps: a job may run minutes, not hours.
MAX_CAL_ITERS = 100
MAX_MORRIS_TRAJECTORIES = 32
MAX_SOBOL_SAMPLES = 128
GSA_DEFAULT_SAMPLES = {"morris": 12, "sobol": 64}
# Governance: caps the compute one organization can hold at once.
ORG_JOB_QUOTA = 2


def _check_caps(n_agents: int, steps: int, seeds: int = 1) -> None:
    for label, value in (("n_agents", n_agents), ("steps", steps), ("seeds", seeds)):
        if value < 1:
            raise ToolError(f"{label}={value} is invalid; {label} must be at least 1.")
    if n_agents > MAX_AGENTS:
        raise ToolError(
            f"n_agents={n_agents} exceeds the per-request cap of {MAX_AGENTS} agents."
        )
    if steps > MAX_STEPS:
        raise ToolError(
            f"steps={steps} exceeds the per-request cap of {MAX_STEPS} steps."
        )
    if seeds > MAX_SEEDS:
        raise ToolError(
            f"seeds={seeds} exceeds the per-request cap of {MAX_SEEDS} seeds."
        )


def _num(x) -> float | None:
    """JSON-safe number: plain float, with NaN (metric undefined) as null."""
    x = float(x)
    return None if math.isnan(x) else x


@mcp.tool
def list_scenarios() -> list[dict]:
    """List the twelve named stress-test scenarios of the DFL24-Sim simulator.

    Each scenario configures a retail crypto market world (market regime,
    adversary campaign, social-engineering wave, or policy design) and carries
    the policy question it answers. Use the returned `name` to run a scenario.
    """
    return [
        {"name": name, "family": family, "question": question}
        for name, family, question in scenarios.list_scenarios()
    ]


@mcp.tool
def run_simulation(
    n_agents: int = 20_000,
    steps: int = 14,
    seed: int = 0,
    adaptive_adversary: bool = False,
    friction_off: bool = False,
    policy_off: bool = False,
) -> dict:
    """Run one simulation of the retail crypto market and return its headline numbers.

    Runs synchronously in a few seconds. Identical inputs always reproduce the
    same result. Caps per request: n_agents <= 100000, steps <= 60 (one step is
    one trading day). Toggles: `adaptive_adversary` lets adversaries learn to
    evade detection rules; `friction_off` removes the point-of-action warning
    prompt; `policy_off` disables all compliance surveillance (laissez-faire).

    Returns, among others: `friction_precision` (share of warnings fired on
    genuinely risky actions), `adversary_detection` (overall share of adversary
    actions caught) with `detection_by_role` rates, `final_trust` (mean user
    trust in the platform, 0-1), `liquidated_frac` and `scam_victim_frac`
    (consumer-harm rates), and the price path extremes.
    """
    _check_caps(n_agents, steps)
    cfg = SimConfig(
        n_agents=n_agents, steps=steps, seed=seed, adaptive_adversary=adaptive_adversary
    )
    if friction_off or policy_off:
        cfg = cfg.with_(
            policy=replace(cfg.policy, friction_off=friction_off, policy_off=policy_off)
        )
    s = run(cfg)["summary"]
    detection_by_role = {
        role: _num(num / max(den, 1))
        for role, (num, den) in s["detection_counts_by_role"].items()
    }
    return {
        "n_agents": int(s["n_agents"]),
        "steps": int(s["steps"]),
        "seed": int(s["seed"]),
        "adaptive_adversary": bool(s["adaptive_adversary"]),
        "friction_off": friction_off,
        "policy_off": policy_off,
        "friction_precision": _num(s["friction_precision"]),
        "friction_on_safe": int(s["friction_on_safe"]),
        "high_risk_attempts": int(s["high_risk_attempts"]),
        "aml_flags": int(s["aml_flags"]),
        "adversary_detection": _num(s["adversary_detection"]),
        "detection_by_role": detection_by_role,
        "final_price": _num(s["final_price"]),
        "max_price": _num(s["max_price"]),
        "min_price": _num(s["min_price"]),
        "liquidated_frac": _num(s["liquidated_frac"]),
        "scam_victim_frac": _num(s["scam_victim_frac"]),
        "final_trust": _num(s["final_trust"]),
        "false_positive_count": int(s["false_positive_count"]),
    }


@mcp.tool
def run_scenario(
    name: str,
    n_agents: int = 15_000,
    steps: int = 14,
    seeds: int = 4,
) -> dict:
    """Run one of the twelve named stress-test scenarios across independent seeds.

    Use list_scenarios for the valid names and the question each scenario
    answers. Runs synchronously (seconds). `seeds` is the number of independent
    replications (seed 0..seeds-1); results report the across-seed mean and its
    Monte-Carlo standard error per metric, plus the per-seed values. Caps per
    request: n_agents <= 100000, steps <= 60, seeds <= 8.

    Key metrics: `coverage` (share of adversary actions detected, with
    `det_*` per adversary class), `precision` (share of friction warnings that
    were justified), `retail_burn` (honest leveraged users ending underwater),
    `liquidated_frac`, `final_trust` (0-1), and for the social-engineering
    scenario the victim take-rates with and without friction
    (`victim_take_control` vs `victim_take_friction`). A metric is null where
    it does not apply to the scenario.
    """
    if name not in scenarios.SCENARIOS:
        raise ToolError(
            f"unknown scenario {name!r}; valid names: {sorted(scenarios.SCENARIOS)}"
        )
    _check_caps(n_agents, steps, seeds)
    agg, df = scenarios.run_scenario(
        name, n_agents=n_agents, steps=steps, seeds=tuple(range(seeds))
    )
    values = df.drop(columns=["seed"])
    se = values.sem(ddof=1) if seeds > 1 else None
    metrics = {
        col: {"mean": _num(agg[col]), "se": _num(se[col]) if se is not None else None}
        for col in values.columns
    }
    per_seed = [
        {"seed": int(row["seed"]), **{c: _num(row[c]) for c in values.columns}}
        for _, row in df.iterrows()
    ]
    return {
        "scenario": name,
        "family": scenarios.SCENARIOS[name]["family"],
        "question": scenarios.SCENARIOS[name]["question"],
        "n_agents": n_agents,
        "steps": steps,
        "seeds": seeds,
        "metrics": metrics,
        "per_seed": per_seed,
    }


@mcp.tool
async def run_study(
    n_agents: int = 15_000, steps: int = 14, seeds: int = 3, force: bool = False
) -> dict:
    """Trigger the full policy × attack study as a background job (fire-and-forget).

    Crosses every policy regime (laissez_faire, standard, over_friction,
    tiered) with every attack world (pump_dump, sybil_farm, laundering,
    adaptive_redteam, pig_butchering) across `seeds` replications — the study
    behind the battery figure. It runs on a worker for minutes: this tool
    returns a `job_id` immediately; check progress with get_job_status and
    fetch the numbers with get_job_result when done. Caps: n_agents <= 100000,
    steps <= 60, seeds <= 8.

    Re-triggering with identical parameters returns the prior completed
    result immediately (`cache_hit: true`) instead of re-running; pass
    `force=true` to re-run anyway. Your organization may hold at most 2
    queued or running jobs across all job types at once.
    """
    _check_caps(n_agents, steps, seeds)
    params = {"n_agents": n_agents, "steps": steps, "seeds": seeds}
    return await _enqueue_job("study", jobs.run_study_job, params, force=force)


def _active_jobs_summary(active: list[dict]) -> str:
    return ", ".join(f"{j['job_id']} ({j['job_type']}, {j['status']})" for j in active)


async def _enqueue_job(
    job_type: str, task, params: dict, force: bool = False
) -> dict:
    org_id = caller_org()
    config_hash = db.config_hash(params)

    # One transaction holds the org's advisory lock across the whole decision:
    # dedup lookup, quota check, and the insert are atomic against concurrent
    # triggers for the same org, so two callers cannot both pass the quota gate
    # and both create a job. The lock releases when this transaction ends.
    async with await psycopg.AsyncConnection.connect(db.get_dsn()) as conn:
        await db.lock_org(conn, org_id)

        if not force:
            cached = await db.cached_job(conn, org_id, job_type, config_hash)
            if cached is not None:
                return {
                    "job_id": cached["job_id"],
                    "status": cached["status"],
                    "job_type": job_type,
                    "config_hash": config_hash,
                    "params": params,
                    "cache_hit": True,
                }

        active = await db.active_jobs(conn, org_id)
        if len(active) >= ORG_JOB_QUOTA:
            raise ToolError(
                f"organization {org_id!r} is at its job quota "
                f"({ORG_JOB_QUOTA} concurrent jobs); active jobs: "
                f"{_active_jobs_summary(active)}. Wait for one to finish or "
                "check its result with get_job_status/get_job_result before "
                "retrying."
            )

        job_id = str(uuid.uuid4())
        await db.create_job(conn, job_id, job_type, params, org_id=org_id)
        await task.configure(connection=conn).defer_async(job_id=job_id, params=params)
        await conn.commit()

    return {
        "job_id": job_id,
        "status": "queued",
        "job_type": job_type,
        "config_hash": config_hash,
        "params": params,
        "cache_hit": False,
    }


@mcp.tool
async def run_calibration(
    n_agents: int = 4000,
    steps: int = 10,
    iters: int = 40,
    n_seeds: int = 3,
    seed: int = 0,
    force: bool = False,
) -> dict:
    """Trigger SMM calibration as a background job (fire-and-forget).

    Re-estimates the headline behavioural parameters by simulated method of
    moments against the field-anchored targets: phi (friction attention boost,
    drives efficacy), eta (habituation rate, drives the fade), a0 (arbitration
    intercept), and beta_r (System-1 risk appetite). Runs on a worker for
    minutes: returns a `job_id` immediately; check progress with
    get_job_status and fetch the fitted parameters and fit diagnostics with
    get_job_result. Caps: n_agents <= 100000, steps <= 60, n_seeds <= 8,
    iters <= 100.

    Re-triggering with identical parameters returns the prior completed
    result immediately (`cache_hit: true`) instead of re-running; pass
    `force=true` to re-run anyway. Your organization may hold at most 2
    queued or running jobs across all job types at once.
    """
    _check_caps(n_agents, steps, n_seeds)
    if not 1 <= iters <= MAX_CAL_ITERS:
        raise ToolError(
            f"iters={iters} is outside the allowed range 1..{MAX_CAL_ITERS}."
        )
    params = {
        "n_agents": n_agents, "steps": steps, "iters": iters,
        "n_seeds": n_seeds, "seed": seed,
    }
    return await _enqueue_job(
        "calibration", jobs.run_calibration_job, params, force=force
    )


@mcp.tool
async def run_gsa(
    method: str = "morris",
    n_agents: int = 3000,
    steps: int = 12,
    samples: int | None = None,
    seed: int = 0,
    force: bool = False,
) -> dict:
    """Trigger global sensitivity analysis as a background job (fire-and-forget).

    Ranks the seven behavioural/market parameters by influence on the four
    headline outputs (efficacy, fade, coverage, trust). `method="morris"` is
    the cheap elementary-effects screening; `samples` is its trajectory count
    (default 12, cap 32; simulation runs = samples x 8). `method="sobol"` is
    the variance decomposition; `samples` is its base sample, a power of two
    (default 64, cap 128; runs = samples x 9). Runs minutes on a worker:
    returns a `job_id` immediately; check with get_job_status and fetch the
    per-parameter indices with get_job_result. Caps: n_agents <= 100000,
    steps <= 60.

    Re-triggering with identical parameters returns the prior completed
    result immediately (`cache_hit: true`) instead of re-running; pass
    `force=true` to re-run anyway. Your organization may hold at most 2
    queued or running jobs across all job types at once.
    """
    if method not in GSA_DEFAULT_SAMPLES:
        raise ToolError(
            f"unknown method {method!r}; valid methods: "
            f"{sorted(GSA_DEFAULT_SAMPLES)}"
        )
    _check_caps(n_agents, steps)
    if samples is None:
        samples = GSA_DEFAULT_SAMPLES[method]
    cap = MAX_MORRIS_TRAJECTORIES if method == "morris" else MAX_SOBOL_SAMPLES
    if not 1 <= samples <= cap:
        raise ToolError(
            f"samples={samples} is outside the allowed range 1..{cap} "
            f"for method {method!r}."
        )
    if method == "sobol" and samples & (samples - 1):
        raise ToolError(f"samples={samples} must be a power of two for sobol.")
    params = {
        "method": method, "n_agents": n_agents, "steps": steps,
        "samples": samples, "seed": seed,
    }
    return await _enqueue_job("gsa", jobs.run_gsa_job, params, force=force)


@mcp.tool
async def run_sweep(
    sweep: str,
    n_agents: int = 6000,
    steps: int = 14,
    seeds: int = 2,
    force: bool = False,
) -> dict:
    """Trigger a one-at-a-time robustness sweep as a background job (fire-and-forget).

    Varies one mechanism over the paper's grid, everything else at the
    calibrated baseline — the check of which white-paper conclusions survive
    miscalibration. Sweeps: `friction_efficacy` (phi -> first-exposure
    effect), `habituation_fade` (eta -> fade ratio), `adaptive_coverage`
    (epsilon -> sybil detection, with the static reference),
    `overfriction_trust` (theta_fa -> trust vs the tiered regime),
    `grooming_victim_reduction` (grooming pressure -> victims saved by
    friction), `margin_systemic` (margin -> liquidations and drawdown). Runs
    minutes on a worker: returns a `job_id` immediately; check with
    get_job_status and fetch the grid of outcomes with get_job_result. Caps:
    n_agents <= 100000, steps <= 60, seeds <= 8.

    Re-triggering with identical parameters returns the prior completed
    result immediately (`cache_hit: true`) instead of re-running; pass
    `force=true` to re-run anyway. Your organization may hold at most 2
    queued or running jobs across all job types at once.
    """
    if sweep not in sweeps.SWEEPS:
        raise ToolError(
            f"unknown sweep {sweep!r}; valid sweeps: {sorted(sweeps.SWEEPS)}"
        )
    _check_caps(n_agents, steps, seeds)
    params = {"sweep": sweep, "n_agents": n_agents, "steps": steps, "seeds": seeds}
    return await _enqueue_job("sweep", jobs.run_sweep_job, params, force=force)


@mcp.tool
def get_reference_results(topic: str | None = None) -> dict:
    """Look up the paper's precomputed headline numbers — no simulation run.

    Serves the research artifacts bundled from the study behind the white
    paper, instantly and with provenance (white-paper section and source
    files). All numbers are simulation results from the DFL24-Sim model —
    not field measurements; repeat that caveat when quoting them. Topics:
    `calibration` (SMM fit, the ~14% first-exposure friction effect),
    `sensitivity` (Morris + Sobol indices, parameter sweeps), `coverage`
    (detection per adversary role, static vs adaptive), `fade` (per-step
    erosion of the friction effect), `battery` (4 policy regimes x 5 attack
    worlds), `validation` (stylized facts, Monte-Carlo convergence). Without
    a topic, lists the supported topics.
    """
    if topic is None:
        return {
            "supported_topics": {
                name: meta["headline"] for name, meta in reference.TOPICS.items()
            },
            "caveat": reference.CAVEAT,
        }
    if topic not in reference.TOPICS:
        raise ToolError(
            f"unknown topic {topic!r}; supported topics: {sorted(reference.TOPICS)}"
        )
    return reference.describe(topic)


def _job_payload(job: dict) -> dict:
    return {
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "params": job["params"],
        "config_hash": job["config_hash"],
        "error": job["error"],
        "warning": job["warning"],
        "created_at": job["created_at"].isoformat(),
        "started_at": job["started_at"].isoformat() if job["started_at"] else None,
        "finished_at": job["finished_at"].isoformat() if job["finished_at"] else None,
    }


def _artifact_listing(job: dict) -> list[dict]:
    # storage keys stay internal; analysts address artifacts by name
    return [
        {"name": a["name"], "kind": a["kind"], "size_bytes": a["size_bytes"]}
        for a in (job["artifacts"] or [])
    ]


@mcp.tool
async def get_job_status(job_id: str | None = None) -> dict:
    """Check on a background job, or list the recent ones.

    With a `job_id`: reports its status — queued, running, done, or failed
    (with the error message when failed). Without: lists the 20 most recent
    jobs, newest first. Results of a done job are fetched with get_job_result.
    """
    org_id = caller_org()
    if job_id is None:
        recent = await db.list_recent(db.get_dsn(), org_id=org_id)
        return {"recent": [_job_payload(job) for job in recent]}
    job = await db.get_job(db.get_dsn(), job_id, org_id=org_id)
    if job is None:
        raise ToolError(f"No job with id {job_id!r}. Use get_job_status without "
                        "arguments to list recent jobs.")
    return _job_payload(job)


@mcp.tool
async def get_job_result(job_id: str) -> dict:
    """Fetch the result of a completed background job (see run_study).

    Only works once get_job_status reports the job as done; errors otherwise
    with the job's current state. For a study job the result contains
    `battery`: one row per policy regime × attack world with `coverage`,
    `retail_burn`, `final_trust`, and `precision` averaged across seeds.
    """
    job = await db.get_job(db.get_dsn(), job_id, org_id=caller_org())
    if job is None:
        raise ToolError(f"No job with id {job_id!r}. Use get_job_status without "
                        "arguments to list recent jobs.")
    if job["status"] != "done":
        detail = f": {job['error']}" if job["error"] else ""
        raise ToolError(
            f"Job {job_id} is {job['status']}{detail}. Results are only "
            "available once get_job_status reports it as done."
        )
    return {
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "params": job["params"],
        "config_hash": job["config_hash"],
        "result": job["result"],
        "artifacts": _artifact_listing(job),
        "warning": job["warning"],
    }


@mcp.tool
async def get_artifact(
    job_id: str, name: str | None = None, expires_in: int = 900
) -> dict:
    """Fetch a completed job's heavy artifacts — figures and data files.

    Without `name`: lists the job's artifacts (name, kind, size_bytes); a
    study job produces `fig_battery.png` (the policy x attack heatmaps) and
    `battery.parquet` (the underlying frame). With `name`: returns a signed
    URL serving that file, valid for `expires_in` seconds (default 15
    minutes, max 24 hours). The JSON summary of get_job_result never needs
    this — object storage only holds the heavy extras.
    """
    job = await db.get_job(db.get_dsn(), job_id, org_id=caller_org())
    if job is None:
        raise ToolError(f"No job with id {job_id!r}. Use get_job_status without "
                        "arguments to list recent jobs.")
    if job["status"] != "done":
        raise ToolError(
            f"Job {job_id} is {job['status']}; artifacts exist once "
            "get_job_status reports it as done."
        )
    listing = _artifact_listing(job)
    if name is None:
        payload = {"job_id": job_id, "artifacts": listing}
        if job["warning"]:
            payload["warning"] = job["warning"]
        return payload
    match = next((a for a in (job["artifacts"] or []) if a["name"] == name), None)
    if match is None:
        raise ToolError(
            f"no artifact {name!r} for job {job_id}; available: "
            f"{sorted(a['name'] for a in listing)}"
        )
    if not 1 <= expires_in <= 86_400:
        raise ToolError(
            f"expires_in={expires_in} is outside the allowed range 1..86400 seconds."
        )
    if not storage.is_configured():
        raise ToolError(
            "object storage is not configured on this server; the artifact "
            "cannot be served."
        )
    return {
        "job_id": job_id,
        "name": match["name"],
        "kind": match["kind"],
        "size_bytes": match["size_bytes"],
        # sign the bucket recorded at upload; rows predating that field fall
        # back to the currently configured bucket
        "url": storage.presign(
            match["key"], expires_in=expires_in, bucket=match.get("bucket")
        ),
        "expires_in_seconds": expires_in,
    }
