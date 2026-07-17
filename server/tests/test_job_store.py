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


async def test_jobs_are_scoped_by_org(job_db):
    job_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", {"n_agents": 100}, org_id="org-a")
        await conn.commit()

    assert (await db.get_job(job_db, job_id))["org_id"] == "org-a"
    assert await db.get_job(job_db, job_id, org_id="org-a") is not None
    # another organization's analyst sees nothing, same as an unknown id
    assert await db.get_job(job_db, job_id, org_id="org-b") is None

    recent_a = await db.list_recent(job_db, org_id="org-a")
    recent_b = await db.list_recent(job_db, org_id="org-b")
    assert job_id in {j["job_id"] for j in recent_a}
    assert job_id not in {j["job_id"] for j in recent_b}


async def test_create_job_defaults_to_the_dev_org(job_db):
    job_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", {"n_agents": 100})
        await conn.commit()

    assert (await db.get_job(job_db, job_id))["org_id"] == "dev"


async def test_list_active_jobs_returns_only_queued_and_running_for_the_org(job_db):
    # the test database isn't truncated between tests, so each test needs its
    # own org id — a literal like "org-a" would pick up other tests' rows
    org_a, org_b = f"org-{uuid.uuid4()}", f"org-{uuid.uuid4()}"

    async def _job(status, org_id):
        job_id = str(uuid.uuid4())
        async with await psycopg.AsyncConnection.connect(job_db) as conn:
            await db.create_job(conn, job_id, "study", {"n": job_id}, org_id=org_id)
            await conn.commit()
        if status == "running":
            db.mark_running(job_db, job_id)
        elif status == "done":
            db.mark_done(job_db, job_id, {})
        elif status == "failed":
            db.mark_failed(job_db, job_id, "boom")
        return job_id

    queued = await _job("queued", org_a)
    running = await _job("running", org_a)
    await _job("done", org_a)
    await _job("failed", org_a)
    other_org_queued = await _job("queued", org_b)

    active = await db.list_active_jobs(job_db, org_a)
    assert {j["job_id"] for j in active} == {queued, running}
    assert {j["job_id"] for j in active}.isdisjoint({other_org_queued})


async def test_find_cached_job_matches_org_type_and_hash(job_db):
    org_a, org_b = f"org-{uuid.uuid4()}", f"org-{uuid.uuid4()}"
    job_id = str(uuid.uuid4())
    params = {"n_agents": 300, "steps": 3, "_nonce": job_id}
    async with await psycopg.AsyncConnection.connect(job_db) as conn:
        await db.create_job(conn, job_id, "study", params, org_id=org_a)
        await conn.commit()
    db.mark_done(job_db, job_id, {"battery": []})

    h = db.config_hash(params)
    hit = await db.find_cached_job(job_db, org_a, "study", h)
    assert hit is not None and hit["job_id"] == job_id

    # a different org, a different job type, and a queued (not done) job
    # must not be returned as a cache hit
    assert await db.find_cached_job(job_db, org_b, "study", h) is None
    assert await db.find_cached_job(job_db, org_a, "calibration", h) is None
    assert await db.find_cached_job(job_db, org_a, "study", "not-a-real-hash") is None


async def test_find_cached_job_prefers_the_most_recent_match(job_db):
    org_a = f"org-{uuid.uuid4()}"
    params = {"n_agents": 300, "_nonce": org_a}
    h = db.config_hash(params)
    ids = []
    for _ in range(2):
        job_id = str(uuid.uuid4())
        async with await psycopg.AsyncConnection.connect(job_db) as conn:
            await db.create_job(conn, job_id, "study", params, org_id=org_a)
            await conn.commit()
        db.mark_done(job_db, job_id, {})
        ids.append(job_id)

    hit = await db.find_cached_job(job_db, org_a, "study", h)
    assert hit["job_id"] == ids[-1]


async def test_get_job_returns_none_for_unknown_id(job_db):
    assert await db.get_job(job_db, str(uuid.uuid4())) is None


def test_config_hash_is_order_independent():
    a = db.config_hash({"n_agents": 500, "steps": 3})
    b = db.config_hash({"steps": 3, "n_agents": 500})
    assert a == b
    assert len(a) == 12
