"""The run_study tool: fire-and-forget triggering of the policy × attack study."""
import time

import psycopg
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db
from dfl24sim_server.mcp import mcp


async def test_run_study_enqueues_and_returns_job_id_fast(job_db):
    async with Client(mcp) as client:
        t0 = time.monotonic()
        r = (
            await client.call_tool(
                "run_study", {"n_agents": 400, "steps": 3, "seeds": 1}
            )
        ).data
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"run_study took {elapsed:.2f}s; must return immediately"
    assert r["status"] == "queued"

    job = await db.get_job(job_db, r["job_id"])
    assert job["status"] == "queued"
    assert job["job_type"] == "study"
    assert job["params"] == {"n_agents": 400, "steps": 3, "seeds": 1}
    assert r["config_hash"] == job["config_hash"]

    # the queue itself must hold a pending job for the worker
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        cur = await conn.execute(
            "SELECT count(*) FROM procrastinate_jobs WHERE status = 'todo'"
        )
        (pending,) = await cur.fetchone()
    assert pending >= 1


async def test_run_study_rejects_over_cap_before_enqueueing(job_db):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="8"):
            await client.call_tool("run_study", {"seeds": 9})
