"""
dfl24sim.calibrate — Simulated Method of Moments (SMM).

Rather than hand-tuning behavioural coefficients, we fit them to target empirical
moments by minimising a weighted distance between simulated and target moments. This
is the standard estimation approach for agent-based / structural models and directly
answers the question "are these numbers calibrated or invented?": the headline
friction parameters are estimated, with the targets anchored on field evidence
(Havakhor et al.'s 8.6-10.5% first-exposure effect) and plausible base rates.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize

from .config import SimConfig, BehaviorParams
from .engine import run as engine_run

# target moments and their (inverse-variance-style) weights
DEFAULT_TARGETS = {
    "first_reduction": 0.095,   # mid Havakhor band
    "control_rate": 0.45,       # baseline first-step high-risk rate
    "fade_ratio": 0.55,         # reduction at last step / first step
}
WEIGHTS = {"first_reduction": 50.0, "control_rate": 2.0, "fade_ratio": 8.0}

# parameters estimated and their bounds
CAL_PARAMS = [
    ("fric_attention", 0.4, 2.2),
    ("s1_risk_app", 1.2, 3.0),
    ("hab_lr", 0.05, 0.40),
    ("arb_intercept", -1.2, 0.8),
]


def _moments(cfg: SimConfig, seeds):
    """Average simulated moments over seeds."""
    firsts, ctrls, fades = [], [], []
    for sd in seeds:
        out = engine_run(cfg.with_(seed=int(sd)), record_panel=False)
        ss = out["summary"]["step_series"]
        by = {}
        for rec in ss:
            by.setdefault((rec["step"], rec["arm"]), rec["high_risk_rate"])
        steps = sorted({k[0] for k in by})
        c0, f0 = by[(steps[0], "control")], by[(steps[0], "friction")]
        cL, fL = by[(steps[-1], "control")], by[(steps[-1], "friction")]
        red0 = (c0 - f0) / c0 if c0 else 0.0
        redL = (cL - fL) / cL if cL else 0.0
        firsts.append(red0); ctrls.append(c0)
        fades.append((redL / red0) if red0 > 1e-6 else 0.0)
    return {"first_reduction": float(np.mean(firsts)),
            "control_rate": float(np.mean(ctrls)),
            "fade_ratio": float(np.clip(np.mean(fades), 0, 2))}


def _params_from_x(x):
    return BehaviorParams(**{name: float(v) for (name, _, _), v in zip(CAL_PARAMS, x)})


def calibrate(targets=None, n_agents=4000, steps=10, iters=40, seed=0, n_seeds=3):
    targets = targets or DEFAULT_TARGETS
    rng = np.random.default_rng(seed)
    seeds = rng.integers(0, 10_000, n_seeds)
    base = SimConfig(n_agents=n_agents, steps=steps, adaptive_adversary=False)

    def loss(x):
        cfg = base.with_(behavior=_params_from_x(x))
        m = _moments(cfg, seeds)
        return sum(WEIGHTS[k] * (m[k] - targets[k]) ** 2 for k in targets)

    x0 = np.array([(lo + hi) / 2 for _, lo, hi in CAL_PARAMS])
    bounds = [(lo, hi) for _, lo, hi in CAL_PARAMS]
    res = minimize(loss, x0, method="Nelder-Mead",
                   options={"maxiter": iters, "xatol": 1e-3, "fatol": 1e-5})
    xhat = np.clip(res.x, [b[0] for b in bounds], [b[1] for b in bounds])
    fitted = _params_from_x(xhat)
    achieved = _moments(base.with_(behavior=fitted), seeds)
    return {
        "estimated": {name: float(v) for (name, _, _), v in zip(CAL_PARAMS, xhat)},
        "targets": targets, "achieved_moments": achieved,
        "loss": float(res.fun), "iterations": int(res.nit), "converged": bool(res.success),
    }
