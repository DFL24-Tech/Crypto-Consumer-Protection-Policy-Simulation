"""The run_gsa tool: Morris/Sobol sensitivity analysis through the job pipeline."""
import time

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db
from dfl24sim_server.mcp import mcp

from conftest import drain_worker

OUTPUTS = {"first_reduction", "fade_ratio", "sybil_coverage", "final_trust"}
PARAMETERS = {
    "phi", "eta", "theta_fa", "epsilon", "maint_margin", "arb_intercept", "beta_r",
}


async def test_run_gsa_enqueues_and_returns_job_id_fast(job_db):
    async with Client(mcp) as client:
        t0 = time.monotonic()
        r = (
            await client.call_tool(
                "run_gsa",
                {"method": "morris", "n_agents": 300, "steps": 3, "samples": 2},
            )
        ).data
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"run_gsa took {elapsed:.2f}s; must return immediately"
    assert r["status"] == "queued"
    assert r["job_type"] == "gsa"
    job = await db.get_job(job_db, r["job_id"])
    assert job["params"]["method"] == "morris"


async def test_run_gsa_validates_method_and_samples(job_db):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="morris"):
            await client.call_tool("run_gsa", {"method": "anova"})
        with pytest.raises(ToolError, match="power of two"):
            await client.call_tool("run_gsa", {"method": "sobol", "samples": 3})
        with pytest.raises(ToolError, match="32"):
            await client.call_tool("run_gsa", {"method": "morris", "samples": 33})
        with pytest.raises(ToolError, match="128"):
            await client.call_tool("run_gsa", {"method": "sobol", "samples": 256})


async def test_morris_job_end_to_end_returns_indices_with_vocabulary(job_db):
    async with Client(mcp) as client:
        r = (
            await client.call_tool(
                "run_gsa",
                {"method": "morris", "n_agents": 300, "steps": 3, "samples": 2},
            )
        ).data
    await drain_worker(job_db)

    async with Client(mcp) as client:
        result = (
            await client.call_tool("get_job_result", {"job_id": r["job_id"]})
        ).data["result"]

    assert result["method"] == "morris"
    assert set(result["index_meanings"]) == {"mu_star", "sigma"}
    outputs = {o["output"]: o for o in result["outputs"]}
    assert set(outputs) == OUTPUTS
    for entry in outputs.values():
        assert entry["meaning"]
        assert {row["parameter"] for row in entry["indices"]} == PARAMETERS
        for row in entry["indices"]:
            assert row["meaning"]
            assert row["mu_star"] is None or isinstance(row["mu_star"], float)
            assert row["sigma"] is None or isinstance(row["sigma"], float)


async def test_sobol_job_end_to_end_returns_first_and_total_order(job_db):
    async with Client(mcp) as client:
        r = (
            await client.call_tool(
                "run_gsa",
                {"method": "sobol", "n_agents": 300, "steps": 3, "samples": 2},
            )
        ).data
    await drain_worker(job_db)

    async with Client(mcp) as client:
        result = (
            await client.call_tool("get_job_result", {"job_id": r["job_id"]})
        ).data["result"]

    assert result["method"] == "sobol"
    assert set(result["index_meanings"]) == {"S1", "ST"}
    for entry in result["outputs"]:
        for row in entry["indices"]:
            # tiny samples can leave an index undefined (NaN -> null)
            assert row["S1"] is None or isinstance(row["S1"], float)
            assert row["ST"] is None or isinstance(row["ST"], float)
