"""
dfl24sim.cli — command-line interface.

  dfl24sim run        --n 100000 --steps 14            single run, prints summary
  dfl24sim batch      --config configs/baseline.yaml --seeds 24 --out results/
  dfl24sim benchmark  --sizes 1000,10000,100000        scaling benchmark
  dfl24sim calibrate  --targets configs/targets.yaml   fit behavioural parameters (SMM)
  dfl24sim study      --out results/                   full staged study + figures
"""
from __future__ import annotations
import argparse, json, time, os
import numpy as np

from .config import SimConfig
from .engine import run as engine_run


def _load_cfg(path):
    if not path:
        return SimConfig()
    import yaml
    with open(path) as f:
        return SimConfig.from_dict(yaml.safe_load(f))


def cmd_run(a):
    cfg = _load_cfg(a.config).with_(n_agents=a.n, steps=a.steps, seed=a.seed,
                                    adaptive_adversary=a.adaptive)
    t = time.time(); out = engine_run(cfg); dt = time.time() - t
    s = out["summary"]
    det = {k: round(v[0] / max(v[1], 1), 3) for k, v in s["detection_counts_by_role"].items()}
    print(f"n={cfg.n_agents} steps={cfg.steps} adaptive={cfg.adaptive_adversary} | {dt:.2f}s")
    print(f"  friction precision {s['friction_precision']:.3f} | on_safe {s['friction_on_safe']}")
    print(f"  detection by role {det}")
    print(f"  price: peak x{s['max_price']:.2f} final x{s['final_price']:.2f}")
    print(f"  network {s['network']}")


def cmd_batch(a):
    from .runner import run_batch
    cfg = _load_cfg(a.config)
    if a.n: cfg = cfg.with_(n_agents=a.n)
    if a.steps: cfg = cfg.with_(steps=a.steps)
    seeds = list(range(a.seeds))
    summ, man = run_batch(cfg, seeds, a.out, workers=a.workers, tag=a.tag)
    print(summ.round(3).to_string(index=False))
    print(f"manifest: {a.out}/{a.tag}_manifest.json  ({man['elapsed_sec']}s, hash {man['config_hash']})")


def cmd_benchmark(a):
    sizes = [int(x) for x in a.sizes.split(",")]
    print(f"{'N':>9} {'sec':>7} {'agent-steps/s':>15} {'precision':>10} {'peak':>6}")
    rows = []
    for N in sizes:
        cfg = SimConfig(n_agents=N, steps=a.steps, seed=0, adaptive_adversary=False)
        t = time.time(); out = engine_run(cfg, record_panel=False); dt = time.time() - t
        s = out["summary"]; rate = N * a.steps / dt
        print(f"{N:>9} {dt:>7.2f} {rate:>15,.0f} {s['friction_precision']:>10.3f} {s['max_price']:>6.2f}")
        rows.append({"n_agents": N, "sec": round(dt, 3), "agent_steps_per_sec": int(rate)})
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump(rows, open(os.path.join(a.out, "benchmark.json"), "w"), indent=2)


def cmd_calibrate(a):
    from .calibrate import calibrate, DEFAULT_TARGETS
    import yaml
    targets = DEFAULT_TARGETS
    if a.targets and os.path.exists(a.targets):
        targets = yaml.safe_load(open(a.targets))
    res = calibrate(targets, n_agents=a.n, steps=a.steps, iters=a.iters, seed=a.seed)
    print(json.dumps(res, indent=2, default=float))
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump(res, open(os.path.join(a.out, "calibration.json"), "w"), indent=2, default=float)


def cmd_scenario(a):
    from . import scenarios as sc
    if a.list:
        for name, fam, q in sc.list_scenarios():
            print(f"[{fam:10}] {name}\n             {q}")
        return
    if a.name and a.name != "all":
        agg, df = sc.run_scenario(a.name, a.n, a.steps, tuple(range(a.seeds)))
        import json; print(json.dumps({k: round(v, 4) if isinstance(v, float) else v
                                       for k, v in agg.items()}, indent=2, default=str))
        return
    summ, bat = sc.run_study(a.out, n_agents=a.n, steps=a.steps, seeds=tuple(range(a.seeds)))
    import pandas as pd
    pd.set_option("display.width", 240, "display.max_columns", 40)
    print(summ.round(3).to_string(index=False))


def cmd_study(a):
    from . import study
    study.run_full(a.out)


def main():
    p = argparse.ArgumentParser(prog="dfl24sim", description="DFL24-Sim v3 platform")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run"); r.add_argument("--config"); r.add_argument("--n", type=int, default=5000)
    r.add_argument("--steps", type=int, default=14); r.add_argument("--seed", type=int, default=0)
    r.add_argument("--adaptive", action="store_true"); r.set_defaults(func=cmd_run)

    b = sub.add_parser("batch"); b.add_argument("--config"); b.add_argument("--n", type=int)
    b.add_argument("--steps", type=int); b.add_argument("--seeds", type=int, default=24)
    b.add_argument("--out", default="results"); b.add_argument("--workers", type=int, default=1)
    b.add_argument("--tag", default="run"); b.set_defaults(func=cmd_batch)

    bm = sub.add_parser("benchmark"); bm.add_argument("--sizes", default="1000,10000,100000")
    bm.add_argument("--steps", type=int, default=14); bm.add_argument("--out", default="")
    bm.set_defaults(func=cmd_benchmark)

    c = sub.add_parser("calibrate"); c.add_argument("--targets"); c.add_argument("--n", type=int, default=4000)
    c.add_argument("--steps", type=int, default=10); c.add_argument("--iters", type=int, default=40)
    c.add_argument("--seed", type=int, default=0); c.add_argument("--out", default="results")
    c.set_defaults(func=cmd_calibrate)

    st = sub.add_parser("study"); st.add_argument("--out", default="results"); st.set_defaults(func=cmd_study)

    sc_p = sub.add_parser("scenario"); sc_p.add_argument("--name", default="all")
    sc_p.add_argument("--list", action="store_true"); sc_p.add_argument("--n", type=int, default=15000)
    sc_p.add_argument("--steps", type=int, default=14); sc_p.add_argument("--seeds", type=int, default=4)
    sc_p.add_argument("--out", default="results/scenarios"); sc_p.set_defaults(func=cmd_scenario)

    a = p.parse_args(); a.func(a)


if __name__ == "__main__":
    main()
