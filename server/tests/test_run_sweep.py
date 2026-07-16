"""The run_sweep tool: one-at-a-time robustness sweeps through the job pipeline."""
import time

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db
from dfl24sim_server.mcp import mcp

from conftest import drain_worker


async def test_run_sweep_enqueues_and_returns_job_id_fast(job_db):
    async with Client(mcp) as client:
        t0 = time.monotonic()
        r = (
            await client.call_tool(
                "run_sweep",
                {"sweep": "friction_efficacy", "n_agents": 300, "steps": 3, "seeds": 1},
            )
        ).data
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"run_sweep took {elapsed:.2f}s; must return immediately"
    assert r["status"] == "queued"
    assert r["job_type"] == "sweep"
    job = await db.get_job(job_db, r["job_id"])
    assert job["params"]["sweep"] == "friction_efficacy"


async def test_run_sweep_rejects_unknown_sweep_and_over_cap(job_db):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="friction_efficacy"):
            await client.call_tool("run_sweep", {"sweep": "vibes"})
        with pytest.raises(ToolError, match="8"):
            await client.call_tool(
                "run_sweep", {"sweep": "friction_efficacy", "seeds": 9}
            )


async def test_sweep_job_end_to_end_returns_grid_with_outcomes(job_db):
    async with Client(mcp) as client:
        r = (
            await client.call_tool(
                "run_sweep",
                {"sweep": "adaptive_coverage", "n_agents": 300, "steps": 3, "seeds": 1},
            )
        ).data
    await drain_worker(job_db)

    async with Client(mcp) as client:
        result = (
            await client.call_tool("get_job_result", {"job_id": r["job_id"]})
        ).data["result"]

    assert result["sweep"] == "adaptive_coverage"
    assert result["parameter"]["symbol"] == "epsilon"
    assert result["parameter"]["meaning"]
    assert result["question"]
    assert result["outcomes"]["sybil_detection"]
    assert len(result["points"]) == 4  # the paper's epsilon grid
    for point in result["points"]:
        assert isinstance(point["value"], float)
        assert point["sybil_detection"] is None or 0.0 <= point["sybil_detection"] <= 1.0
    assert "static_detection" in result["reference"]
