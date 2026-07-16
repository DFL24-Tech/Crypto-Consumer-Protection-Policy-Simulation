"""
dfl24sim.gsa — global sensitivity analysis (Morris screening, Sobol indices).

The library form of the paper's gsa_morris.py / gsa_sobol.py drivers: the same
seven-parameter problem and four-output model, parameterized by population
size, horizon, and sample count so it can run as a background job. The world
is the D2 over-friction scenario with adaptive adversaries — the setting where
every mechanism (efficacy, fade, coverage, trust) is active at once.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import scenarios as sc
from .engine import run as engine_run

# order matters: positions map onto sample columns and index arrays
PARAMETER_NAMES = [
    "phi", "eta", "theta_fa", "epsilon", "maint_margin", "arb_intercept", "beta_r",
]
PARAMETER_BOUNDS = [
    [0.6, 1.7], [0.0, 0.6], [0.0, 0.2], [0.05, 0.4],
    [0.3, 0.75], [-0.5, 0.1], [1.5, 3.0],
]
OUTPUT_NAMES = ["first_reduction", "fade_ratio", "sybil_coverage", "final_trust"]


def _problem() -> dict:
    return {
        "num_vars": len(PARAMETER_NAMES),
        "names": PARAMETER_NAMES,
        "bounds": PARAMETER_BOUNDS,
    }


def _first_reduction_and_fade(summary: dict) -> tuple[float, float]:
    by = {}
    for rec in summary["step_series"]:
        by[(rec["step"], rec["arm"])] = rec["high_risk_rate"]
    steps = sorted({k[0] for k in by})
    c0, f0 = by[(steps[0], "control")], by[(steps[0], "friction")]
    cL, fL = by[(steps[-1], "control")], by[(steps[-1], "friction")]
    r0 = (c0 - f0) / c0 if c0 else 0.0
    rL = (cL - fL) / cL if cL else 0.0
    return r0, ((rL / r0) if r0 > 1e-6 else 0.0)


def _evaluate(x, n_agents: int, steps: int) -> list[float]:
    phi, eta, tfa, eps, mm, arb, br = [float(v) for v in x]
    cfg = sc.build("D2_over_friction_fatigue", n_agents, steps, 0).with_(
        adaptive_adversary=True, bandit_epsilon=eps
    )
    cfg = cfg.with_(
        behavior=replace(
            cfg.behavior, fric_attention=phi, hab_lr=eta,
            trust_false_alarm=tfa, arb_intercept=arb, s1_risk_app=br,
        )
    )
    cfg = cfg.with_(market=replace(cfg.market, maint_margin=mm))
    s = engine_run(cfg, record_panel=False)["summary"]
    r0, fade = _first_reduction_and_fade(s)
    detected, total = s["detection_counts_by_role"]["sybil_attacker"]
    return [r0, fade, detected / max(total, 1), s["final_trust"]]


def _model_outputs(X, n_agents: int, steps: int) -> np.ndarray:
    return np.array([_evaluate(x, n_agents, steps) for x in X])


def run_morris(
    n_agents: int = 3000,
    steps: int = 12,
    trajectories: int = 12,
    num_levels: int = 6,
    seed: int = 0,
) -> dict:
    """Morris elementary-effects screening; mu_star ranks parameter influence."""
    from SALib.analyze import morris as morris_analyze
    from SALib.sample.morris import sample as morris_sample

    problem = _problem()
    X = morris_sample(problem, N=trajectories, num_levels=num_levels, seed=seed)
    Y = _model_outputs(X, n_agents, steps)
    result = {}
    for j, output in enumerate(OUTPUT_NAMES):
        Si = morris_analyze.analyze(problem, X, Y[:, j], num_levels=num_levels)
        result[output] = {
            "names": PARAMETER_NAMES,
            "mu_star": [float(v) for v in Si["mu_star"]],
            "sigma": [float(v) for v in Si["sigma"]],
        }
    return result


def run_sobol(
    n_agents: int = 3000,
    steps: int = 12,
    base_samples: int = 64,
    seed: int = 0,
) -> dict:
    """Sobol variance decomposition; S1 first-order, ST total-order indices."""
    from SALib.analyze import sobol as sobol_analyze
    from SALib.sample.sobol import sample as sobol_sample

    problem = _problem()
    X = sobol_sample(problem, base_samples, calc_second_order=False, seed=seed)
    Y = _model_outputs(X, n_agents, steps)
    result = {}
    for j, output in enumerate(OUTPUT_NAMES):
        Si = sobol_analyze.analyze(problem, Y[:, j], calc_second_order=False)
        result[output] = {
            "names": PARAMETER_NAMES,
            "S1": [float(v) for v in Si["S1"]],
            "ST": [float(v) for v in Si["ST"]],
        }
    return result
