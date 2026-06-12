"""
dfl24sim.study — headline analyses at platform scale, with confidence intervals and
publication figures. Runs many seeds at large N and aggregates; the genuine findings
(coverage gap, adaptive robustness, systemic risk) and the emergent behavioural effect
are reported with Wilson / percentile intervals.
"""
from __future__ import annotations
import os, json, time
import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from .config import SimConfig, ADV_NAME_LIST
from .engine import run as engine_run

INK = "#1B1F3B"; ACCENT = "#C9A24B"; RULE = "#C0392B"; GREY = "#5B6170"; GREEN = "#2E7D32"
NICE = {"sybil_attacker": "Sybil", "market_manipulator": "Manipulator",
        "money_launderer": "Launderer", "cyber_red_team": "Cyber"}
sns.set_theme(style="whitegrid")
plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "axes.titlecolor": INK})


def wilson(k, n, z=1.96):
    if n <= 0:
        return (float("nan"),) * 3
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0, c - h), min(1, c + h)


def coverage(n_agents, steps, seeds, adaptive):
    num = {r: 0 for r in ADV_NAME_LIST}; den = {r: 0 for r in ADV_NAME_LIST}
    for sd in seeds:
        s = engine_run(SimConfig(n_agents=n_agents, steps=steps, seed=int(sd),
                                 adaptive_adversary=adaptive), record_panel=False)["summary"]
        for r, (k, d) in s["detection_counts_by_role"].items():
            num[r] += k; den[r] += d
    rows = []
    for r in ADV_NAME_LIST:
        if den[r] == 0:
            continue
        p, lo, hi = wilson(num[r], den[r])
        rows.append(dict(role=r, detected=num[r], total=den[r], rate=p, lo=lo, hi=hi))
    return pd.DataFrame(rows)


def systemic(n_agents, steps, seeds):
    peaks, crashes, burned = [], [], []
    for sd in seeds:
        out = engine_run(SimConfig(n_agents=n_agents, steps=steps, seed=int(sd),
                                   adaptive_adversary=False), record_panel=False)
        path = np.array(out["summary"]["price_path"])
        pk = path.max(); idx = int(path.argmax()); trough = path[idx:].min()
        st = out["state"]
        chasers = st.took_leverage & ~st.is_adv
        if chasers.any():
            burned.append(float((st.hr_leverage_pnl[chasers] < 0).mean()))
        peaks.append(pk); crashes.append((pk - trough) / pk)
    ci = lambda a: (float(np.mean(a)), float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))
    return dict(peak=ci(peaks), crash=ci(crashes), burned=ci(burned) if burned else (float("nan"),)*3)


def fade(n_agents, steps, seeds):
    acc = {}
    for sd in seeds:
        s = engine_run(SimConfig(n_agents=n_agents, steps=steps, seed=int(sd),
                                 adaptive_adversary=False), record_panel=False)["summary"]
        for rec in s["step_series"]:
            acc.setdefault((rec["step"], rec["arm"]), []).append(rec["high_risk_rate"])
    steps_i = sorted({k[0] for k in acc})
    rows = []
    for st in steps_i:
        c = np.array(acc[(st, "control")]); f = np.array(acc[(st, "friction")])
        rows.append(dict(step=st, control=c.mean(), friction=f.mean(),
                         reduction=(c.mean() - f.mean()) / c.mean() if c.mean() else 0))
    return pd.DataFrame(rows)


def run_full(out_dir, n_agents=20000, steps=14, n_seeds=12):
    os.makedirs(out_dir, exist_ok=True)
    seeds = list(range(n_seeds))
    t0 = time.time()

    print(f"[study] N={n_agents}, {n_seeds} seeds, steps={steps}")
    cov = coverage(n_agents, steps, seeds, adaptive=False)
    cov.to_csv(f"{out_dir}/coverage.csv", index=False)
    adapt = coverage(n_agents, steps, seeds, adaptive=True)
    adapt.to_csv(f"{out_dir}/coverage_adaptive.csv", index=False)
    fd = fade(n_agents, steps, seeds); fd.to_csv(f"{out_dir}/fade.csv", index=False)
    sysr = systemic(n_agents, steps, seeds)
    json.dump(sysr, open(f"{out_dir}/systemic.json", "w"), indent=2, default=float)

    # ---- benchmark for the scaling figure ----
    bench = []
    for N in (1000, 5000, 20000, 50000, 100000):
        t = time.time()
        engine_run(SimConfig(n_agents=N, steps=steps, seed=0, adaptive_adversary=False),
                   record_panel=False)
        dt = time.time() - t
        bench.append({"n_agents": N, "sec": dt, "rate": N * steps / dt})
    bdf = pd.DataFrame(bench); bdf.to_csv(f"{out_dir}/benchmark.csv", index=False)

    _figures(out_dir, cov, adapt, fd, sysr, bdf)
    summary = {
        "n_agents": n_agents, "n_seeds": n_seeds, "steps": steps,
        "coverage": {r.role: dict(rate=r.rate, lo=r.lo, hi=r.hi) for r in cov.itertuples()},
        "systemic": {"peak": sysr["peak"][0], "crash": sysr["crash"][0], "burned": sysr["burned"][0]},
        "max_throughput_agent_steps_per_sec": int(bdf.rate.max()),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    json.dump(summary, open(f"{out_dir}/summary.json", "w"), indent=2, default=float)
    print(json.dumps(summary, indent=2, default=float))


def _figures(out, cov, adapt, fd, sysr, bdf):
    # scaling benchmark
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    ax.plot(bdf.n_agents, bdf.sec, "-o", color=INK, lw=2)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Population size (agents)"); ax.set_ylabel("Wall-clock seconds (14 steps)")
    for _, r in bdf.iterrows():
        ax.annotate(f"{int(r.rate/1000)}k a·s/s", (r.n_agents, r.sec),
                    fontsize=8, xytext=(4, -10), textcoords="offset points")
    ax.set_title("Near-linear scaling to 10⁵ agents (vectorised engine)")
    fig.savefig(f"{out}/fig_scaling.png"); plt.close(fig)

    # coverage static vs adaptive
    cc = cov.set_index("role"); aa = adapt.set_index("role")
    order = [r for r in ["sybil_attacker", "market_manipulator", "money_launderer", "cyber_red_team"] if r in cc.index]
    x = np.arange(len(order)); w = 0.38
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.bar(x - w/2, [cc.loc[r, "rate"] for r in order], w, color=INK, label="Static adversary")
    ax.bar(x + w/2, [aa.loc[r, "rate"] if r in aa.index else 0 for r in order], w, color=RULE,
           label="Adaptive (learns to evade)")
    ax.set_xticks(x); ax.set_xticklabels([NICE[r] for r in order]); ax.set_ylim(0, 1.1)
    ax.set_ylabel("Detection rate"); ax.legend(frameon=False)
    ax.set_title("Coverage gap and its collapse under adaptation")
    fig.savefig(f"{out}/fig_coverage.png"); plt.close(fig)

    # fade
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    ax.plot(fd.step, fd.control*100, "-o", color=GREY, lw=2, label="Control")
    ax.plot(fd.step, fd.friction*100, "-o", color=INK, lw=2, label="Friction")
    ax.fill_between(fd.step, fd.friction*100, fd.control*100, color=ACCENT, alpha=.25)
    ax.set_xlabel("Step"); ax.set_ylabel("High-risk action rate (%)")
    ax.set_title("Friction fades with exposure (emergent)"); ax.legend(frameon=False)
    fig.savefig(f"{out}/fig_fade.png"); plt.close(fig)
    print("  figures:", [f for f in os.listdir(out) if f.startswith("fig_")])
