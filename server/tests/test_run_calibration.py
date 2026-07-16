"""The run_calibration tool: SMM calibration through the job pipeline."""
import time

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db
from dfl24sim_server.mcp import mcp

from conftest import drain_worker

FAST = {"n_agents": 300, "steps": 3, "iters": 2, "n_seeds": 1}


async def test_run_calibration_enqueues_and_returns_job_id_fast(job_db):
    async with Client(mcp) as client:
        t0 = time.monotonic()
        r = (await client.call_tool("run_calibration", FAST)).data
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"run_calibration took {elapsed:.2f}s; must return immediately"
    assert r["status"] == "queued"
    assert r["job_type"] == "calibration"

    job = await db.get_job(job_db, r["job_id"])
    assert job["status"] == "queued"
    assert job["job_type"] == "calibration"
    assert job["params"]["iters"] == 2


async def test_run_calibration_rejects_over_cap_before_enqueueing(job_db):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="iters"):
            await client.call_tool("run_calibration", {"iters": 101})
        with pytest.raises(ToolError, match="8"):
            await client.call_tool("run_calibration", {"n_seeds": 9})


async def test_calibration_job_end_to_end_returns_documented_fit(job_db):
    async with Client(mcp) as client:
        r = (await client.call_tool("run_calibration", FAST)).data
    await drain_worker(job_db)

    async with Client(mcp) as client:
        result = (
            await client.call_tool("get_job_result", {"job_id": r["job_id"]})
        ).data["result"]

    estimated = {p["name"]: p for p in result["estimated_parameters"]}
    assert set(estimated) == {"fric_attention", "s1_risk_app", "hab_lr", "arb_intercept"}
    assert estimated["fric_attention"]["symbol"] == "phi"
    assert estimated["hab_lr"]["symbol"] == "eta"
    for param in estimated.values():
        assert param["meaning"]
        assert isinstance(param["value"], float)

    fit = result["fit"]
    assert isinstance(fit["converged"], bool)
    assert isinstance(fit["loss"], float)
    assert fit["iterations"] >= 1

    moments = {m["name"]: m for m in result["moments"]}
    assert set(moments) == {"first_reduction", "control_rate", "fade_ratio"}
    for moment in moments.values():
        assert moment["meaning"]
        assert isinstance(moment["target"], float)
        assert isinstance(moment["achieved"], float)
