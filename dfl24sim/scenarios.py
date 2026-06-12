"""
dfl24sim.scenarios — named scenarios and the stress-test battery.

A scenario is a coherent configuration of the six axes (market, population, network,
behaviour, policy, adversary), each carrying a specific question. The battery runs a
fixed policy across a suite of adversary/market worlds to find where it breaks — the
deliverable a sandbox/regulator actually needs.
"""
from __future__ import annotations
from dataclasses import replace
import numpy as np
import pandas as pd

from .config import (SimConfig, BehaviorParams, MarketParams, PolicyParams,
                     NetworkParams, PopulationParams)
from .engine import run as engine_run


# ---- scenario registry: name -> (family, question, overrides) -----------------------
# overrides is a dict with optional keys: sim, market, population, policy, behavior, network
SCENARIOS = {
    # ===== A. Market regimes & shocks =====
    "A1_calm_baseline": dict(
        family="Market", question="Reference point: friction/coverage in a normal market.",
        sim=dict(adaptive_adversary=False)),
    "A2_retail_mania": dict(
        family="Market", question="Does friction survive when everyone is euphoric and herding (contagion dominates)? How far does leverage build?",
        market=dict(regime="bull", bull_drift=0.045, contagion_mult=2.6, dump_intensity=2.5, leverage_max=18),
        population=dict(p_manipulator=0.5, p_sybil=0.3, p_launderer=0.15, p_cyber=0.05),
        behavior=dict(s1_social=2.4)),
    "A3_crash_cascade": dict(
        family="Market", question="When a dump triggers liquidations that cascade over leverage, how many burn and how far does trust fall?",
        market=dict(liquidation=True, maint_margin=0.45, liq_pressure=4.0, dump_intensity=2.8, leverage_max=20)),
    "A4_exogenous_shock": dict(
        family="Market", question="Resilience to an exogenous shock (a depeg), distinct from an endogenous bubble.",
        market=dict(shock_step=7, shock_size=-0.42, liquidation=True, maint_margin=0.5)),

    # ===== B. Adversary campaigns =====
    "B1_pump_and_dump_ring": dict(
        family="Adversary", question="Does market-integrity surveillance catch a thin-liquidity pump, and does friction shield retail chasers?",
        market=dict(depth_ref=4000.0, manip_pressure=9.0, dump_intensity=2.5),
        population=dict(p_manipulator=0.6, p_sybil=0.2, p_launderer=0.15, p_cyber=0.05)),
    "B2_sybil_airdrop_farm": dict(
        family="Adversary", question="How much of a sybil farm does the cluster rule catch, and how does it collapse under adaptation?",
        sim=dict(adaptive_adversary=True),
        population=dict(adversary_mix=0.15, p_manipulator=0.15, p_sybil=0.65, p_launderer=0.15, p_cyber=0.05)),
    "B3_laundering_layering": dict(
        family="Adversary", question="What share of layering does AML catch when launderers adapt to evade?",
        sim=dict(adaptive_adversary=True),
        population=dict(p_manipulator=0.15, p_sybil=0.2, p_launderer=0.6, p_cyber=0.05)),
    "B4_adaptive_red_team": dict(
        family="Adversary", question="Worst-case coverage: every adversary learns, exploration high.",
        sim=dict(adaptive_adversary=True, bandit_epsilon=0.25),
        population=dict(adversary_mix=0.18)),

    # ===== C. Social engineering =====
    "C1_pig_butchering_wave": dict(
        family="Social-eng", question="When scammers groom victims over the social graph, can point-of-action friction stop the payment, or is the deliberate valuation already corrupted?",
        population=dict(scammer_frac=0.035),
        behavior=dict(groom_strength=0.35)),

    # ===== D. Policy design =====
    "D1_laissez_faire": dict(
        family="Policy", question="Counterfactual floor: what happens with no friction and no compliance?",
        policy=dict(friction_off=True, policy_off=True)),
    "D2_over_friction_fatigue": dict(
        family="Policy", question="Does over-friction backfire (false positives erode trust and habituate the prompt, so it fails when it matters)?",
        policy=dict(false_positive_rate=0.55)),
    "D3_vifc_tiered_sandbox": dict(
        family="Policy", question="Which tiering balances protection against friction/trust cost? (DFL24's 3-tier sandbox.)",
        policy=dict(tiered=True)),
}


def _apply(base: SimConfig, ov: dict) -> SimConfig:
    cfg = base
    if "sim" in ov:
        cfg = cfg.with_(**ov["sim"])
    for key, cls_attr in [("market", "market"), ("population", "population"),
                          ("policy", "policy"), ("behavior", "behavior"), ("network", "network")]:
        if key in ov:
            sub = getattr(cfg, cls_attr)
            cfg = cfg.with_(**{cls_attr: replace(sub, **ov[key])})
    return cfg


def build(name: str, n_agents=20000, steps=14, seed=0) -> SimConfig:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; options: {list(SCENARIOS)}")
    # scenarios are static by default; only those that opt in (B2/B3/B4) become adaptive
    base = SimConfig(n_agents=n_agents, steps=steps, seed=seed, adaptive_adversary=False)
    return _apply(base, SCENARIOS[name])


def list_scenarios():
    return [(k, v["family"], v["question"]) for k, v in SCENARIOS.items()]


def _metrics(out):
    """Headline metrics shared across scenarios."""
    s = out["summary"]; stt = out["state"]
    honest = ~stt.is_adv
    det = {r: (k / max(d, 1)) for r, (k, d) in s["detection_counts_by_role"].items()}
    # retail harm: honest agents who took leverage and ended underwater
    chasers = honest & stt.took_leverage
    retail_burn = float((stt.hr_leverage_pnl[chasers] < 0).mean()) if chasers.any() else 0.0
    m = {
        "coverage": s["adversary_detection"],
        "det_manipulator": det.get("market_manipulator", float("nan")),
        "det_sybil": det.get("sybil_attacker", float("nan")),
        "det_launderer": det.get("money_launderer", float("nan")),
        "det_cyber": det.get("cyber_red_team", float("nan")),
        "precision": s["friction_precision"], "on_safe": s["friction_on_safe"],
        "peak": s["max_price"], "trough_drawdown": (s["max_price"] - s["min_price"]) / s["max_price"],
        "retail_burn": retail_burn, "liquidated_frac": s["liquidated_frac"],
        "final_trust": s["final_trust"], "false_positives": s["false_positive_count"],
        "scam_victim_frac": s["scam_victim_frac"],
    }
    vs = out["summary"].get("victim_series", [])
    if vs:
        m["victim_take_control"] = float(np.mean([r["take_rate"] for r in vs if r["arm"] == "control"]))
        m["victim_take_friction"] = float(np.mean([r["take_rate"] for r in vs if r["arm"] == "friction"]))
    else:
        m["victim_take_control"] = float("nan"); m["victim_take_friction"] = float("nan")
    return m


def run_scenario(name, n_agents=20000, steps=14, seeds=(0, 1, 2, 3)):
    rows = []
    for sd in seeds:
        out = engine_run(build(name, n_agents, steps, int(sd)), record_panel=False)
        m = _metrics(out); m["seed"] = sd; rows.append(m)
    df = pd.DataFrame(rows)
    agg = df.drop(columns=["seed"]).mean().to_dict()
    agg["scenario"] = name; agg["family"] = SCENARIOS[name]["family"]
    return agg, df


def run_all(n_agents=15000, steps=14, seeds=(0, 1, 2, 3, 4)):
    """Run all 12 scenarios; return a tidy comparison frame."""
    rows = []
    for name in SCENARIOS:
        agg, _ = run_scenario(name, n_agents, steps, seeds)
        rows.append(agg)
    cols = ["scenario", "family", "coverage", "det_sybil", "det_manipulator",
            "det_launderer", "det_cyber", "precision", "on_safe", "peak",
            "trough_drawdown", "retail_burn", "liquidated_frac", "final_trust",
            "false_positives", "scam_victim_frac"]
    return pd.DataFrame(rows)[cols]


# ---- battery: a fixed policy across many worlds -------------------------------------
POLICY_REGIMES = {
    "laissez_faire": dict(policy=dict(friction_off=True, policy_off=True)),
    "standard": dict(),                                   # friction + policy on (defaults)
    "over_friction": dict(policy=dict(false_positive_rate=0.55)),
    "tiered": dict(policy=dict(tiered=True)),
}
ATTACK_WORLDS = {
    "pump_dump": "B1_pump_and_dump_ring",
    "sybil_farm": "B2_sybil_airdrop_farm",
    "laundering": "B3_laundering_layering",
    "adaptive_redteam": "B4_adaptive_red_team",
    "pig_butchering": "C1_pig_butchering_wave",
}


def run_battery(n_agents=15000, steps=14, seeds=(0, 1, 2)):
    """Cross every policy regime with every attack world; report the metric matrix."""
    records = []
    for pol_name, pol_ov in POLICY_REGIMES.items():
        for atk_name, atk_scn in ATTACK_WORLDS.items():
            ov = dict(SCENARIOS[atk_scn])           # attack overrides
            # merge policy regime on top (policy + sim overrides win)
            merged = {k: dict(v) for k, v in ov.items() if k in ("sim", "market", "population", "policy", "behavior", "network")}
            for k, v in pol_ov.items():
                merged.setdefault(k, {}).update(v)
            cov, burn, trust, prec = [], [], [], []
            for sd in seeds:
                cfg = _apply(SimConfig(n_agents=n_agents, steps=steps, seed=int(sd),
                                       adaptive_adversary=False), merged)
                out = engine_run(cfg, record_panel=False)
                m = _metrics(out)
                cov.append(m["coverage"]); burn.append(m["retail_burn"])
                trust.append(m["final_trust"]); prec.append(m["precision"])
            records.append(dict(policy=pol_name, attack=atk_name,
                                coverage=float(np.mean(cov)), retail_burn=float(np.mean(burn)),
                                final_trust=float(np.mean(trust)), precision=float(np.mean(prec))))
    return pd.DataFrame(records)


# ---- scenario study: run everything, save tables + figures --------------------------
def run_study(out_dir, n_agents=15000, steps=14, seeds=(0, 1, 2, 3)):
    import os, json
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    os.makedirs(out_dir, exist_ok=True)
    INK, ACCENT, RULE, GREY, GREEN = "#1B1F3B", "#C9A24B", "#C0392B", "#5B6170", "#2E7D32"
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight"})

    # all 12 scenarios
    summ = run_all(n_agents, steps, seeds)
    summ.to_csv(f"{out_dir}/scenarios_summary.csv", index=False)
    # battery
    bat = run_battery(n_agents, steps, seeds[:3])
    bat.to_csv(f"{out_dir}/battery.csv", index=False)

    # representative market price paths (single seed)
    paths = {}
    for nm, lab in [("A1_calm_baseline", "Calm"), ("A2_retail_mania", "Mania"),
                    ("A4_exogenous_shock", "Depeg shock"), ("B1_pump_and_dump_ring", "Pump-and-dump")]:
        out = engine_run(build(nm, n_agents, steps, 0), record_panel=False)
        paths[lab] = out["summary"]["price_path"]

    # Figure 1: market regimes
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for (lab, p), col in zip(paths.items(), [GREY, GREEN, RULE, INK]):
        ax.plot(p, lw=2, label=lab, color=col)
    ax.axhline(1.0, ls=":", color="k", alpha=.4)
    ax.set_xlabel("Step"); ax.set_ylabel("Price (× fundamental)")
    ax.set_title("Distinct market regimes across scenarios"); ax.legend(frameon=False)
    fig.savefig(f"{out_dir}/fig_scenario_markets.png"); plt.close(fig)

    # Figure 2: battery heatmaps (coverage + trust)
    cov = bat.pivot(index="policy", columns="attack", values="coverage")
    tr = bat.pivot(index="policy", columns="attack", values="final_trust")
    order = ["laissez_faire", "standard", "over_friction", "tiered"]
    cov = cov.reindex(order); tr = tr.reindex(order)
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.6))
    sns.heatmap(cov, annot=True, fmt=".2f", cmap="Blues", ax=axes[0], cbar_kws={"label": "coverage"})
    axes[0].set_title("Adversary detection by policy × attack")
    sns.heatmap(tr, annot=True, fmt=".2f", cmap="RdYlGn", ax=axes[1], vmin=0.4, vmax=0.65,
                cbar_kws={"label": "final trust"})
    axes[1].set_title("User trust by policy × attack")
    for a in axes:
        a.set_xlabel(""); a.set_ylabel("")
    fig.tight_layout(); fig.savefig(f"{out_dir}/fig_battery.png"); plt.close(fig)

    # Figure 3: policy trade-off (coverage vs trust) — shows over-friction dominated
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    agg = bat.groupby("policy").agg(coverage=("coverage", "mean"), trust=("final_trust", "mean")).reindex(order)
    cols = {"laissez_faire": GREY, "standard": INK, "over_friction": RULE, "tiered": ACCENT}
    for pol_name, row in agg.iterrows():
        ax.scatter(row["coverage"], row["trust"], s=160, color=cols[pol_name], zorder=3)
        ax.annotate(pol_name, (row["coverage"], row["trust"]), xytext=(6, 4),
                    textcoords="offset points", fontsize=9)
    ax.set_xlabel("Mean coverage (higher = safer)"); ax.set_ylabel("Mean final trust (higher = better UX)")
    ax.set_title("Policy trade-off: over-friction is dominated")
    fig.savefig(f"{out_dir}/fig_policy_tradeoff.png"); plt.close(fig)

    # Figure 4: C1 grooming — friction helps normal agents but not groomed victims
    out = engine_run(build("C1_pig_butchering_wave", n_agents, steps, 0), record_panel=False)
    vs = out["summary"]["victim_series"]
    vc = np.mean([r["take_rate"] for r in vs if r["arm"] == "control"])
    vf = np.mean([r["take_rate"] for r in vs if r["arm"] == "friction"])
    ss = out["summary"]["step_series"]
    nc = np.mean([r["high_risk_rate"] for r in ss if r["arm"] == "control"])
    nf = np.mean([r["high_risk_rate"] for r in ss if r["arm"] == "friction"])
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    x = np.arange(2); w = 0.36
    ax.bar(x - w/2, [nc, vc], w, color=GREY, label="Control")
    ax.bar(x + w/2, [nf, vf], w, color=INK, label="Friction")
    ax.set_xticks(x); ax.set_xticklabels(["General population", "Groomed victims"])
    ax.set_ylabel("High-risk take rate")
    ax.set_title("Friction protects the crowd, not the groomed victim"); ax.legend(frameon=False)
    for i, (c, f) in enumerate([(nc, nf), (vc, vf)]):
        red = (c - f) / c * 100 if c else 0
        ax.annotate(f"−{red:.0f}%", (i, max(c, f) + 0.02), ha="center", color=RULE, fontsize=10)
    fig.savefig(f"{out_dir}/fig_grooming.png"); plt.close(fig)

    meta = {"n_agents": n_agents, "steps": steps, "seeds": list(seeds),
            "scenarios": len(SCENARIOS),
            "figures": ["fig_scenario_markets", "fig_battery", "fig_policy_tradeoff", "fig_grooming"]}
    json.dump(meta, open(f"{out_dir}/scenario_meta.json", "w"), indent=2)
    print("scenarios:", len(SCENARIOS), "| battery cells:", len(bat), "| figures: 4")
    return summ, bat
