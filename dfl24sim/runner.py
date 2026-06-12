"""
dfl24sim.runner — reproducible batch execution.

Runs a config across many seeds (optionally in parallel), writes per-run summaries and
the first-step panel to Parquet, and emits a JSON manifest capturing the exact config,
library versions, and seeds — so every result is traceable to the inputs that produced
it. This is the provenance layer that turns ad-hoc scripts into an experiment platform.
"""
from __future__ import annotations
import os, json, time, platform, hashlib
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

from .config import SimConfig
from .engine import run as engine_run


def _run_one(args):
    cfg_dict, seed = args
    cfg = SimConfig.from_dict(cfg_dict).with_(seed=seed)
    out = engine_run(cfg, record_panel=True)
    s = out["summary"]
    row = {
        "seed": seed, "n_agents": s["n_agents"], "steps": s["steps"],
        "adaptive": s["adaptive_adversary"], "friction_precision": s["friction_precision"],
        "friction_on_safe": s["friction_on_safe"], "final_price": s["final_price"],
        "max_price": s["max_price"], "adversary_detection": s["adversary_detection"],
    }
    for r, (num, den) in s["detection_counts_by_role"].items():
        row[f"det_{r}"] = num / max(den, 1)
    return row, out["panel_first"], s["price_path"], s["step_series"]


def run_batch(cfg: SimConfig, seeds, out_dir, workers=1, tag="run"):
    os.makedirs(out_dir, exist_ok=True)
    cfg_dict = cfg.to_dict()
    t0 = time.time()
    args = [(cfg_dict, int(s)) for s in seeds]
    rows, panels, paths, series = [], [], [], []
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for row, panel, path, ss in ex.map(_run_one, args):
                rows.append(row); panels.append(panel); paths.append(path); series.append(ss)
    else:
        for a in args:
            row, panel, path, ss = _run_one(a)
            rows.append(row); panels.append(panel); paths.append(path); series.append(ss)
    elapsed = time.time() - t0

    summ_df = pd.DataFrame(rows)
    summ_df.to_parquet(os.path.join(out_dir, f"{tag}_summary.parquet"))
    # first-step panel of the first seed (representative, for heterogeneity at scale)
    if panels and panels[0] is not None:
        pdf = pd.DataFrame({k: v for k, v in panels[0].items()})
        pdf.to_parquet(os.path.join(out_dir, f"{tag}_panel.parquet"))
    # mean price path across seeds
    mlen = min(len(p) for p in paths)
    parr = np.array([p[:mlen] for p in paths])
    pd.DataFrame({"step": range(mlen), "price_mean": parr.mean(0),
                  "price_lo": np.percentile(parr, 2.5, 0),
                  "price_hi": np.percentile(parr, 97.5, 0)}).to_parquet(
        os.path.join(out_dir, f"{tag}_price.parquet"))

    manifest = {
        "tag": tag, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_sec": round(elapsed, 3), "n_runs": len(seeds), "workers": workers,
        "config": cfg_dict, "config_hash": hashlib.sha1(json.dumps(cfg_dict, sort_keys=True).encode()).hexdigest()[:12],
        "seeds": [int(s) for s in seeds],
        "environment": {"python": platform.python_version(),
                        "numpy": np.__version__, "pandas": pd.__version__,
                        "platform": platform.platform()},
    }
    json.dump(manifest, open(os.path.join(out_dir, f"{tag}_manifest.json"), "w"), indent=2)
    return summ_df, manifest
