"""get_job_status and get_job_result: how an analyst follows up on a triggered job."""
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server.mcp import mcp

from conftest import drain_worker

TINY = {"n_agents": 300, "steps": 3, "seeds": 1}


async def test_get_job_status_follows_the_lifecycle(job_db):
    async with Client(mcp) as client:
        job_id = (await client.call_tool("run_study", TINY)).data["job_id"]

        before = (await client.call_tool("get_job_status", {"job_id": job_id})).data
        assert before["status"] == "queued"
        assert before["job_type"] == "study"
        assert before["created_at"]

        await drain_worker(job_db)

        after = (await client.call_tool("get_job_status", {"job_id": job_id})).data
        assert after["status"] == "done"
        assert after["finished_at"]


async def test_get_job_status_without_id_lists_recent_jobs(job_db):
    async with Client(mcp) as client:
        first = (await client.call_tool("run_study", TINY)).data["job_id"]
        second = (await client.call_tool("run_study", TINY)).data["job_id"]

        listing = (await client.call_tool("get_job_status", {})).data
        recent_ids = [j["job_id"] for j in listing["recent"]]
        assert second in recent_ids and first in recent_ids
        # newest first
        assert recent_ids.index(second) < recent_ids.index(first)


async def test_get_job_status_unknown_id_errors(job_db):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="[Nn]o job"):
            await client.call_tool(
                "get_job_status", {"job_id": "00000000-0000-0000-0000-000000000000"}
            )


async def test_get_job_result_returns_study_summary_when_done(job_db):
    async with Client(mcp) as client:
        job_id = (await client.call_tool("run_study", TINY)).data["job_id"]
        await drain_worker(job_db)

        result = (await client.call_tool("get_job_result", {"job_id": job_id})).data
        assert result["status"] == "done"
        assert len(result["result"]["battery"]) == 20


async def test_get_job_result_before_completion_explains_status(job_db):
    async with Client(mcp) as client:
        job_id = (await client.call_tool("run_study", TINY)).data["job_id"]
        with pytest.raises(ToolError, match="queued"):
            await client.call_tool("get_job_result", {"job_id": job_id})
