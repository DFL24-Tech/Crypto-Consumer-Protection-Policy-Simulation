"""The procrastinate app and job tasks executed by the worker."""
import procrastinate

from dfl24sim import scenarios

from . import db

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=db.get_dsn())
)


def _execute_study(params: dict) -> dict:
    df = scenarios.run_battery(
        n_agents=params["n_agents"],
        steps=params["steps"],
        seeds=tuple(range(params["seeds"])),
    )
    return {"battery": df.to_dict(orient="records")}


@app.task(name="dfl24sim.run_study")
def run_study_job(job_id: str, params: dict) -> None:
    dsn = db.get_dsn()
    db.mark_running(dsn, job_id)
    try:
        result = _execute_study(params)
    except Exception as exc:
        db.mark_failed(dsn, job_id, f"{type(exc).__name__}: {exc}")
        raise
    db.mark_done(dsn, job_id, result)
