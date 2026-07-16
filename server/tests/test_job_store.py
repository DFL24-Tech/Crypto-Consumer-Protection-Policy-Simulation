"""Job rows in Postgres: the metadata store behind the async job tools."""
import uuid

import psycopg

from dfl24sim_server import db


async def test_create_and_get_job_roundtrip(job_db):
    job_id = str(uuid.uuid4())
    params = {"n_agents": 500, "steps": 3, "seeds": 1}

    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", params)
        await conn.commit()

    job = await db.get_job(job_db, job_id)
    assert job["job_id"] == job_id
    assert job["job_type"] == "study"
    assert job["status"] == "queued"
    assert job["params"] == params
    assert job["config_hash"] == db.config_hash(params)
    assert job["created_at"] is not None
    assert job["error"] is None


async def test_mark_done_stores_artifacts_and_warning(job_db):
    job_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", {"n_agents": 500})
        await conn.commit()

    artifacts = [{"name": "fig_battery.png", "key": f"jobs/{job_id}/fig_battery.png",
                  "size_bytes": 123, "content_type": "image/png"}]
    db.mark_done(job_db, job_id, {"battery": []}, artifacts=artifacts,
                 warning="artifact upload failed: boom")

    job = await db.get_job(job_db, job_id)
    assert job["status"] == "done"
    assert job["artifacts"] == artifacts
    assert job["warning"] == "artifact upload failed: boom"


async def test_mark_done_without_artifacts_leaves_them_null(job_db):
    job_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "calibration", {"iters": 2})
        await conn.commit()

    db.mark_done(job_db, job_id, {"fit": {}})

    job = await db.get_job(job_db, job_id)
    assert job["artifacts"] is None
    assert job["warning"] is None


async def test_get_job_returns_none_for_unknown_id(job_db):
    assert await db.get_job(job_db, str(uuid.uuid4())) is None


def test_config_hash_is_order_independent():
    a = db.config_hash({"n_agents": 500, "steps": 3})
    b = db.config_hash({"steps": 3, "n_agents": 500})
    assert a == b
    assert len(a) == 12
