"""The procrastinate app and job tasks executed by the worker."""
import io
import math
from dataclasses import dataclass

import procrastinate

from dfl24sim import gsa, scenarios, sweeps
from dfl24sim.calibrate import calibrate

from . import db, storage

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=db.get_dsn())
)


@dataclass
class ArtifactFile:
    """A heavy job output bound for object storage, never for Postgres."""
    name: str
    kind: str  # "figure" | "data"
    content_type: str
    data: bytes


def _json_safe(value):
    """Postgres JSONB rejects NaN/Infinity; represent an undefined metric as null."""
    if isinstance(value, dict):
        return {key: _json_safe(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _store_artifacts(
    job_id: str, files: list[ArtifactFile]
) -> tuple[list | None, str | None]:
    """Upload what we can; a storage problem is a warning, never a job failure."""
    if not files:
        return None, None
    if not storage.is_configured():
        return None, (
            "object storage not configured (DFL24_S3_ENDPOINT unset); "
            "artifacts were skipped"
        )
    stored = []
    try:
        for file in files:
            meta = storage.upload(job_id, file.name, file.data, file.content_type)
            stored.append({**meta, "kind": file.kind})
    except Exception as exc:
        return (
            stored or None,
            f"artifact upload failed: {type(exc).__name__}: {exc}",
        )
    return stored, None


def _run_tracked(job_id: str, params: dict, execute) -> None:
    dsn = db.get_dsn()
    db.mark_running(dsn, job_id)
    try:
        result, files = execute(params)
        result = _json_safe(result)
    except Exception as exc:
        db.mark_failed(dsn, job_id, f"{type(exc).__name__}: {exc}")
        raise
    artifacts, warning = _store_artifacts(job_id, files)
    db.mark_done(dsn, job_id, result, artifacts=artifacts, warning=warning)


def _execute_study(params: dict) -> tuple[dict, list[ArtifactFile]]:
    import matplotlib.pyplot as plt

    df = scenarios.run_battery(
        n_agents=params["n_agents"],
        steps=params["steps"],
        seeds=tuple(range(params["seeds"])),
    )
    parquet_buf = io.BytesIO()
    df.to_parquet(parquet_buf)
    fig = scenarios.battery_figure(df)
    png_buf = io.BytesIO()
    try:
        fig.savefig(png_buf, format="png")
    finally:
        plt.close(fig)  # a leaked figure accumulates in the long-lived worker
    files = [
        ArtifactFile(
            "battery.parquet", "data",
            "application/vnd.apache.parquet", parquet_buf.getvalue(),
        ),
        ArtifactFile("fig_battery.png", "figure", "image/png", png_buf.getvalue()),
    ]
    return {"battery": df.to_dict(orient="records")}, files


# The summary schemas below are the LLM's reading material: field names and
# embedded meanings speak the analyst vocabulary (efficacy, fade, coverage,
# trust), not internal symbols alone.
_CAL_PARAM_VOCAB = {
    "fric_attention": (
        "phi", "friction attention boost — drives first-exposure efficacy"
    ),
    "s1_risk_app": (
        "beta_r", "System-1 risk-appetite weight — baseline appetite for the "
        "high-risk action"
    ),
    "hab_lr": (
        "eta", "habituation learning rate — drives how fast the friction "
        "effect fades"
    ),
    "arb_intercept": (
        "a0", "arbitration intercept — baseline share of deliberate "
        "(System-2) decisions"
    ),
}
_MOMENT_VOCAB = {
    "first_reduction": "efficacy: first-exposure reduction in the high-risk "
                       "take-rate from the friction prompt",
    "control_rate": "baseline first-step high-risk take-rate in the control arm",
    "fade_ratio": "fade: last-step reduction over first-step reduction "
                  "(1.0 = no fade)",
}


def _execute_calibration(params: dict) -> tuple[dict, list[ArtifactFile]]:
    res = calibrate(
        n_agents=params["n_agents"],
        steps=params["steps"],
        iters=params["iters"],
        seed=params["seed"],
        n_seeds=params["n_seeds"],
    )
    return {
        "estimated_parameters": [
            {
                "name": name,
                "symbol": symbol,
                "value": res["estimated"][name],
                "meaning": meaning,
            }
            for name, (symbol, meaning) in _CAL_PARAM_VOCAB.items()
        ],
        "fit": {
            "loss": res["loss"],
            "iterations": res["iterations"],
            "converged": res["converged"],
        },
        "moments": [
            {
                "name": name,
                "meaning": meaning,
                "target": res["targets"][name],
                "achieved": res["achieved_moments"][name],
            }
            for name, meaning in _MOMENT_VOCAB.items()
        ],
    }, []


_GSA_PARAM_VOCAB = {
    "phi": "friction attention boost — drives efficacy",
    "eta": "habituation learning rate — drives the fade",
    "theta_fa": "trust penalty per false alarm — drives trust",
    "epsilon": "adversary exploration rate — drives the coverage gap",
    "maint_margin": "maintenance margin — the forced-liquidation threshold",
    "arb_intercept": "arbitration intercept — baseline share of deliberate "
                     "(System-2) decisions",
    "beta_r": "System-1 risk-appetite weight — baseline risk-taking",
}
_GSA_OUTPUT_VOCAB = {
    "first_reduction": "efficacy: first-exposure reduction in the high-risk "
                       "take-rate from the friction prompt",
    "fade_ratio": "fade: last-step reduction over first-step reduction "
                  "(1.0 = no fade)",
    "sybil_coverage": "coverage: share of sybil-attacker actions detected",
    "final_trust": "trust: mean end-of-run user trust in the platform (0-1)",
}
_GSA_INDEX_VOCAB = {
    "morris": {
        "mu_star": "mean absolute elementary effect — overall influence of "
                   "the parameter on the output",
        "sigma": "spread of elementary effects — nonlinearity or "
                 "interactions with other parameters",
    },
    "sobol": {
        "S1": "first-order Sobol index — share of output variance the "
              "parameter explains alone",
        "ST": "total-order Sobol index — share including all interactions",
    },
}


def _execute_gsa(params: dict) -> tuple[dict, list[ArtifactFile]]:
    method = params["method"]
    if method not in _GSA_INDEX_VOCAB:
        # the tool validates too; guard here so a corrupt job row fails
        # before minutes of sampling, not after
        raise ValueError(f"unknown gsa method {method!r}")
    if method == "morris":
        raw = gsa.run_morris(
            n_agents=params["n_agents"], steps=params["steps"],
            trajectories=params["samples"], seed=params["seed"],
        )
    else:
        raw = gsa.run_sobol(
            n_agents=params["n_agents"], steps=params["steps"],
            base_samples=params["samples"], seed=params["seed"],
        )
    index_keys = tuple(_GSA_INDEX_VOCAB[method])
    outputs = []
    for output, indices in raw.items():
        rows = []
        for i, parameter in enumerate(indices["names"]):
            row = {"parameter": parameter, "meaning": _GSA_PARAM_VOCAB[parameter]}
            for key in index_keys:
                row[key] = indices[key][i]
            rows.append(row)
        outputs.append({
            "output": output,
            "meaning": _GSA_OUTPUT_VOCAB[output],
            "indices": rows,
        })
    return {
        "method": method,
        "index_meanings": _GSA_INDEX_VOCAB[method],
        "outputs": outputs,
    }, []


@app.task(name="dfl24sim.run_study")
def run_study_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_study)


@app.task(name="dfl24sim.run_calibration")
def run_calibration_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_calibration)


def _execute_sweep(params: dict) -> tuple[dict, list[ArtifactFile]]:
    # the sweeps module carries the analyst vocabulary itself
    return sweeps.run_sweep(
        params["sweep"],
        n_agents=params["n_agents"],
        steps=params["steps"],
        seeds=tuple(range(params["seeds"])),
    ), []


@app.task(name="dfl24sim.run_gsa")
def run_gsa_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_gsa)


@app.task(name="dfl24sim.run_sweep")
def run_sweep_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_sweep)
