"""The DFL24-Sim MCP server: tools a policy analyst's LLM can call."""
import math
from dataclasses import replace

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from dfl24sim import SimConfig, run, scenarios

mcp = FastMCP("DFL24-Sim")

# Hard per-request caps: tool calls run synchronously inside a chat turn, so a
# request must stay in the seconds range on one worker.
MAX_AGENTS = 100_000
MAX_STEPS = 60
MAX_SEEDS = 8


def _check_caps(n_agents: int, steps: int, seeds: int = 1) -> None:
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
