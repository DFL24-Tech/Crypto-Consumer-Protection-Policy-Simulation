"""The get_artifact tool: listings and signed URLs for a completed job's files."""
import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server.mcp import mcp

from conftest import drain_worker

FAST = {"n_agents": 300, "steps": 3, "seeds": 1}


async def _finished_study(client: Client, job_db) -> str:
    r = (await client.call_tool("run_study", FAST)).data
    await drain_worker(job_db)
    return r["job_id"]


async def test_get_artifact_lists_names_kinds_and_sizes(job_db, artifact_store):
    async with Client(mcp) as client:
        job_id = await _finished_study(client, job_db)
        listing = (await client.call_tool("get_artifact", {"job_id": job_id})).data

    by_name = {a["name"]: a for a in listing["artifacts"]}
    assert set(by_name) == {"battery.parquet", "fig_battery.png"}
    assert by_name["fig_battery.png"]["kind"] == "figure"
    for artifact in by_name.values():
        assert artifact["size_bytes"] > 0
        assert "key" not in artifact  # storage keys stay internal


async def test_get_artifact_signs_a_working_expiring_url(job_db, artifact_store):
    async with Client(mcp) as client:
        job_id = await _finished_study(client, job_db)
        signed = (
            await client.call_tool(
                "get_artifact",
                {"job_id": job_id, "name": "fig_battery.png", "expires_in": 60},
            )
        ).data

    assert signed["name"] == "fig_battery.png"
    assert signed["expires_in_seconds"] == 60
    response = httpx.get(signed["url"])
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


async def test_get_artifact_rejects_unknown_names_jobs_and_unfinished_jobs(
    job_db, artifact_store
):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="job"):
            await client.call_tool("get_artifact", {"job_id": "nope"})

        queued = (await client.call_tool("run_study", FAST)).data
        with pytest.raises(ToolError, match="queued"):
            await client.call_tool("get_artifact", {"job_id": queued["job_id"]})

        await drain_worker(job_db)
        with pytest.raises(ToolError, match="fig_battery.png"):
            await client.call_tool(
                "get_artifact", {"job_id": queued["job_id"], "name": "nope.png"}
            )


async def test_get_job_result_includes_artifact_listing(job_db, artifact_store):
    async with Client(mcp) as client:
        job_id = await _finished_study(client, job_db)
        result = (await client.call_tool("get_job_result", {"job_id": job_id})).data

    assert {a["name"] for a in result["artifacts"]} == {
        "battery.parquet", "fig_battery.png",
    }
    assert len(result["result"]["battery"]) == 20


async def test_get_job_status_surfaces_the_storage_warning(job_db, monkeypatch):
    monkeypatch.setenv("DFL24_S3_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("DFL24_S3_ACCESS_KEY", "x")
    monkeypatch.setenv("DFL24_S3_SECRET_KEY", "x")

    async with Client(mcp) as client:
        job_id = await _finished_study(client, job_db)
        status = (await client.call_tool("get_job_status", {"job_id": job_id})).data

    assert status["status"] == "done"
    assert "artifact upload failed" in status["warning"]
