"""The worker: drains queued jobs and writes results/failures to the job store."""
from fastmcp import Client

from dfl24sim_server import db
from dfl24sim_server.mcp import mcp

from conftest import drain_worker


async def test_worker_processes_study_job_end_to_end(job_db):
    async with Client(mcp) as client:
        r = (
            await client.call_tool(
                "run_study", {"n_agents": 300, "steps": 3, "seeds": 1}
            )
        ).data
    job_id = r["job_id"]
    assert (await db.get_job(job_db, job_id))["status"] == "queued"

    await drain_worker(job_db)

    job = await db.get_job(job_db, job_id)
    assert job["status"] == "done"
    assert job["started_at"] is not None
    assert job["finished_at"] is not None
    assert job["error"] is None

    battery = job["result"]["battery"]
    assert len(battery) == 20  # 4 policy regimes x 5 attack worlds
    assert {row["policy"] for row in battery} == {
        "laissez_faire", "standard", "over_friction", "tiered",
    }
    assert {row["attack"] for row in battery} == {
        "pump_dump", "sybil_farm", "laundering", "adaptive_redteam", "pig_butchering",
    }
    for row in battery:
        for metric in ("coverage", "retail_burn", "final_trust", "precision"):
            assert metric in row, f"battery row missing {metric}"


async def test_worker_marks_poisoned_job_failed_with_the_error(job_db):
    """A job whose parameters crash the engine ends failed, error preserved."""
    import uuid

    import psycopg

    from dfl24sim_server import jobs

    job_id = str(uuid.uuid4())
    poisoned = {"n_agents": -5, "steps": 3, "seeds": 1}  # bypasses tool validation
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", poisoned)
        await jobs.run_study_job.configure(connection=conn).defer_async(
            job_id=job_id, params=poisoned
        )
        await conn.commit()

    await drain_worker(job_db)

    job = await db.get_job(job_db, job_id)
    assert job["status"] == "failed"
    assert job["error"]
    assert job["result"] is None
    assert job["finished_at"] is not None
