"""
dfl24sim.sweeps — one-at-a-time robustness sweeps (library form of sweep.py).

Each sweep varies one mechanism over the paper's grid, everything else at the
calibrated baseline, and reports the outcome that mechanism drives — the test
of which white-paper conclusions survive miscalibration. Vocabulary lives here
with the science: parameters and outcomes carry analyst-facing meanings
(efficacy, fade, coverage, trust) alongside the internal names.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import scenarios as sc
from .config import SimConfig
from .engine import run as engine_run
from .gsa import _first_reduction_and_fade

# calibrated anchors (results/calibration.json), as in the paper's sweep.py
_CALIBRATED = {"fric_attention": 1.13, "hab_lr": 0.228}


def _baseline_cfg(n_agents, steps, seed, **behavior_overrides) -> SimConfig:
    cfg = SimConfig(n_agents=n_agents, steps=steps, seed=seed)
    overrides = {**_CALIBRATED, **behavior_overrides}
    return cfg.with_(behavior=replace(cfg.behavior, **overrides))


def _mean(values) -> float:
    return float(np.mean(values))


def _sybil_detection(out) -> float:
    detected, total = out["summary"]["detection_counts_by_role"]["sybil_attacker"]
    return detected / max(total, 1)


def _sweep_friction_efficacy(grid, n_agents, steps, seeds):
    points = []
    for phi in grid:
        vals = [
            _first_reduction_and_fade(
                engine_run(
                    _baseline_cfg(n_agents, steps, sd, fric_attention=phi),
                    record_panel=False,
                )["summary"]
            )[0]
            for sd in seeds
        ]
        points.append({"value": phi, "first_reduction": _mean(vals)})
    return points, None


def _sweep_habituation_fade(grid, n_agents, steps, seeds):
    points = []
    for eta in grid:
        vals = [
            _first_reduction_and_fade(
                engine_run(
                    _baseline_cfg(n_agents, steps, sd, hab_lr=eta),
                    record_panel=False,
                )["summary"]
            )[1]
            for sd in seeds
        ]
        points.append({"value": eta, "fade_ratio": _mean(vals)})
    return points, None


def _sweep_adaptive_coverage(grid, n_agents, steps, seeds):
    static = _mean([
        _sybil_detection(engine_run(
            sc.build("B4_adaptive_red_team", n_agents, steps, sd).with_(
                adaptive_adversary=False
            ),
            record_panel=False,
        ))
        for sd in seeds
    ])
    points = []
    for eps in grid:
        vals = [
            _sybil_detection(engine_run(
                sc.build("B4_adaptive_red_team", n_agents, steps, sd).with_(
                    adaptive_adversary=True, bandit_epsilon=eps
                ),
                record_panel=False,
            ))
            for sd in seeds
        ]
        points.append({"value": eps, "sybil_detection": _mean(vals)})
    return points, {"static_detection": static}


def _sweep_overfriction_trust(grid, n_agents, steps, seeds):
    standard = _mean([
        sc._metrics(engine_run(
            sc.build("D3_vifc_tiered_sandbox", n_agents, steps, sd),
            record_panel=False,
        ))["final_trust"]
        for sd in seeds
    ])
    points = []
    for fa_penalty in grid:
        vals = []
        for sd in seeds:
            cfg = sc.build("D2_over_friction_fatigue", n_agents, steps, sd)
            cfg = cfg.with_(behavior=replace(cfg.behavior, trust_false_alarm=fa_penalty))
            vals.append(sc._metrics(engine_run(cfg, record_panel=False))["final_trust"])
        points.append({"value": fa_penalty, "final_trust": _mean(vals)})
    return points, {"standard_trust": standard}


def _sweep_grooming_victim_reduction(grid, n_agents, steps, seeds):
    points = []
    for groom in grid:
        vals = []
        for sd in seeds:
            cfg = sc.build("C1_pig_butchering_wave", n_agents, steps, sd)
            cfg = cfg.with_(behavior=replace(cfg.behavior, groom_strength=groom))
            m = sc._metrics(engine_run(cfg, record_panel=False))
            vc, vf = m["victim_take_control"], m["victim_take_friction"]
            vals.append((vc - vf) / vc if vc > 1e-6 else 0.0)
        points.append({"value": groom, "victim_reduction": _mean(vals)})
    return points, None


def _sweep_margin_systemic(grid, n_agents, steps, seeds):
    points = []
    for margin in grid:
        liquidated, drawdown = [], []
        for sd in seeds:
            cfg = sc.build("A3_crash_cascade", n_agents, steps, sd)
            cfg = cfg.with_(market=replace(cfg.market, maint_margin=margin))
            m = sc._metrics(engine_run(cfg, record_panel=False))
            liquidated.append(m["liquidated_frac"])
            drawdown.append(m["trough_drawdown"])
        points.append({
            "value": margin,
            "liquidated_frac": _mean(liquidated),
            "trough_drawdown": _mean(drawdown),
        })
    return points, None


SWEEPS = {
    "friction_efficacy": {
        "parameter": {
            "name": "fric_attention", "symbol": "phi",
            "meaning": "friction attention boost — how strongly the warning "
                       "prompt shifts a decision toward deliberate thinking",
        },
        "grid": (0.6, 0.9, 1.13, 1.4, 1.7),
        "outcomes": {
            "first_reduction": "efficacy: first-exposure reduction in the "
                               "high-risk take-rate from the friction prompt",
        },
        "question": "does the headline friction effect survive miscalibration of phi?",
        "_run": _sweep_friction_efficacy,
    },
    "habituation_fade": {
        "parameter": {
            "name": "hab_lr", "symbol": "eta",
            "meaning": "habituation learning rate — how quickly prompt "
                       "salience decays with repeated exposure",
        },
        "grid": (0.0, 0.1, 0.228, 0.4, 0.6),
        "outcomes": {
            "fade_ratio": "fade: last-step reduction over first-step "
                          "reduction (1.0 = no fade, below 1 = effect erodes)",
        },
        "question": "is the fade emergent from habituation, vanishing at eta=0?",
        "_run": _sweep_habituation_fade,
    },
    "adaptive_coverage": {
        "parameter": {
            "name": "bandit_epsilon", "symbol": "epsilon",
            "meaning": "adversary exploration rate — how aggressively "
                       "adversaries try new evasion tactics",
        },
        "grid": (0.05, 0.15, 0.25, 0.4),
        "outcomes": {
            "sybil_detection": "coverage: share of sybil-attacker actions "
                               "detected by the rule-based surveillance",
        },
        "question": "how far does adaptive evasion collapse the static "
                    "detection rate (see reference.static_detection)?",
        "_run": _sweep_adaptive_coverage,
    },
    "overfriction_trust": {
        "parameter": {
            "name": "trust_false_alarm", "symbol": "theta_fa",
            "meaning": "trust penalty per false alarm — how much an "
                       "unjustified warning erodes user trust",
        },
        "grid": (0.0, 0.05, 0.1, 0.2),
        "outcomes": {
            "final_trust": "trust: mean end-of-run user trust (0-1) under "
                           "the over-friction regime",
        },
        "question": "does over-friction backfire on trust versus the tiered "
                    "regime (see reference.standard_trust)?",
        "_run": _sweep_overfriction_trust,
    },
    "grooming_victim_reduction": {
        "parameter": {
            "name": "groom_strength", "symbol": "groom",
            "meaning": "strength of the social-engineering grooming pressure "
                       "on targeted victims",
        },
        "grid": (0.0, 0.1, 0.2, 0.35, 0.5),
        "outcomes": {
            "victim_reduction": "share of groomed payment victims the "
                                "friction prompt prevents",
        },
        "question": "can friction still stop a groomed payment as grooming "
                    "pressure rises?",
        "_run": _sweep_grooming_victim_reduction,
    },
    "margin_systemic": {
        "parameter": {
            "name": "maint_margin", "symbol": "maint_margin",
            "meaning": "maintenance margin — the equity floor below which a "
                       "leveraged position is force-liquidated",
        },
        "grid": (0.3, 0.45, 0.6, 0.75),
        "outcomes": {
            "liquidated_frac": "share of leveraged users force-liquidated in "
                               "the crash cascade",
            "trough_drawdown": "peak-to-trough price drawdown of the cascade",
        },
        "question": "how does the margin rule trade liquidation harm against "
                    "cascade depth?",
        "_run": _sweep_margin_systemic,
    },
}


def run_sweep(name: str, n_agents: int = 6000, steps: int = 14, seeds=(0, 1)) -> dict:
    """Run one named sweep; returns the grid points with outcome values."""
    if name not in SWEEPS:
        raise ValueError(f"unknown sweep {name!r}; valid names: {sorted(SWEEPS)}")
    meta = SWEEPS[name]
    points, reference = meta["_run"](meta["grid"], n_agents, steps, tuple(seeds))
    result = {
        "sweep": name,
        "parameter": meta["parameter"],
        "question": meta["question"],
        "outcomes": meta["outcomes"],
        "points": points,
    }
    if reference is not None:
        result["reference"] = reference
    return result
