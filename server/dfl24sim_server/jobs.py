"""The procrastinate app and job tasks executed by the worker."""
import math

import procrastinate

from dfl24sim import gsa, scenarios, sweeps
from dfl24sim.calibrate import calibrate

from . import db

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=db.get_dsn())
)


def _json_safe(value):
    """Postgres JSONB rejects NaN/Infinity; represent an undefined metric as null."""
    if isinstance(value, dict):
        return {key: _json_safe(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _run_tracked(job_id: str, params: dict, execute) -> None:
    dsn = db.get_dsn()
    db.mark_running(dsn, job_id)
    try:
        result = _json_safe(execute(params))
    except Exception as exc:
        db.mark_failed(dsn, job_id, f"{type(exc).__name__}: {exc}")
        raise
    db.mark_done(dsn, job_id, result)


def _execute_study(params: dict) -> dict:
    df = scenarios.run_battery(
        n_agents=params["n_agents"],
        steps=params["steps"],
        seeds=tuple(range(params["seeds"])),
    )
    return {"battery": df.to_dict(orient="records")}


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


def _execute_calibration(params: dict) -> dict:
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
    }


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


def _execute_gsa(params: dict) -> dict:
    method = params["method"]
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
    }


@app.task(name="dfl24sim.run_study")
def run_study_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_study)


@app.task(name="dfl24sim.run_calibration")
def run_calibration_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_calibration)


def _execute_sweep(params: dict) -> dict:
    # the sweeps module carries the analyst vocabulary itself
    return sweeps.run_sweep(
        params["sweep"],
        n_agents=params["n_agents"],
        steps=params["steps"],
        seeds=tuple(range(params["seeds"])),
    )


@app.task(name="dfl24sim.run_gsa")
def run_gsa_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_gsa)


@app.task(name="dfl24sim.run_sweep")
def run_sweep_job(job_id: str, params: dict) -> None:
    _run_tracked(job_id, params, _execute_sweep)
