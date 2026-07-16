"""Artifact uploads from the worker: study figures/parquet land in object storage.

The JSON-numbers-first contract: summaries live in Postgres and survive even
when object storage is down or absent — a lost figure is a warning, never a
failed job.
"""
import io

import httpx
import pandas as pd
from fastmcp import Client

from dfl24sim_server import db, storage
from dfl24sim_server.mcp import mcp

from conftest import drain_worker

FAST = {"n_agents": 300, "steps": 3, "seeds": 1}


async def _run_study_job(job_db) -> dict:
    async with Client(mcp) as client:
        r = (await client.call_tool("run_study", FAST)).data
    await drain_worker(job_db)
    return await db.get_job(job_db, r["job_id"])


async def test_study_job_uploads_battery_figure_and_parquet(job_db, artifact_store):
    job = await _run_study_job(job_db)

    assert job["status"] == "done"
    assert job["warning"] is None
    artifacts = {a["name"]: a for a in job["artifacts"]}
    assert set(artifacts) == {"battery.parquet", "fig_battery.png"}
    assert artifacts["fig_battery.png"]["kind"] == "figure"
    assert artifacts["battery.parquet"]["kind"] == "data"
    for artifact in artifacts.values():
        assert artifact["size_bytes"] > 0
        assert artifact["key"].startswith(f"jobs/{job['job_id']}/")

    # the uploaded parquet is the battery, not just bytes
    url = storage.presign(artifacts["battery.parquet"]["key"], expires_in=60)
    frame = pd.read_parquet(io.BytesIO(httpx.get(url).content))
    assert len(frame) == 20


async def test_study_job_completes_with_warning_when_storage_is_down(
    job_db, monkeypatch
):
    monkeypatch.setenv("DFL24_S3_ENDPOINT", "http://127.0.0.1:9")  # closed port
    monkeypatch.setenv("DFL24_S3_ACCESS_KEY", "x")
    monkeypatch.setenv("DFL24_S3_SECRET_KEY", "x")

    job = await _run_study_job(job_db)

    assert job["status"] == "done"
    assert len(job["result"]["battery"]) == 20  # numbers survived
    assert "artifact upload failed" in job["warning"]


async def test_study_job_without_storage_configured_warns_and_keeps_numbers(
    job_db, monkeypatch
):
    monkeypatch.delenv("DFL24_S3_ENDPOINT", raising=False)

    job = await _run_study_job(job_db)

    assert job["status"] == "done"
    assert len(job["result"]["battery"]) == 20
    assert job["artifacts"] is None
    assert "not configured" in job["warning"]


async def test_jobs_without_files_carry_no_artifacts_or_warning(job_db, artifact_store):
    async with Client(mcp) as client:
        r = (
            await client.call_tool(
                "run_calibration",
                {"n_agents": 300, "steps": 3, "iters": 2, "n_seeds": 1},
            )
        ).data
    await drain_worker(job_db)

    job = await db.get_job(job_db, r["job_id"])
    assert job["status"] == "done"
    assert job["artifacts"] is None
    assert job["warning"] is None
