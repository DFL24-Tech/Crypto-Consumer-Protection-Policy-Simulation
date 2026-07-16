"""Postgres job store: metadata and results for the async job pipeline."""
import hashlib
import json
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DEFAULT_DSN = "postgresql://dfl24:dfl24@localhost:5432/dfl24sim"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sim_jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    params JSONB NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    result JSONB,
    error TEXT,
    artifacts JSONB,
    warning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
-- additive migration for deployments created before artifact storage
ALTER TABLE sim_jobs ADD COLUMN IF NOT EXISTS artifacts JSONB;
ALTER TABLE sim_jobs ADD COLUMN IF NOT EXISTS warning TEXT;
CREATE INDEX IF NOT EXISTS sim_jobs_created_idx ON sim_jobs (created_at DESC);
"""

_JOB_COLUMNS = (
    "id, job_type, params, config_hash, status, result, error, "
    "artifacts, warning, created_at, started_at, finished_at"
)


def get_dsn() -> str:
    return os.environ.get("DFL24_DATABASE_URL", DEFAULT_DSN)


def config_hash(params: dict) -> str:
    """Same recipe as the runner manifests: sha1 of the sorted-key JSON."""
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]


def apply_schema(dsn: str) -> None:
    import procrastinate

    from .jobs import app  # imported lazily: jobs.py imports this module

    with psycopg.connect(dsn) as conn:
        cur = conn.execute("SELECT to_regclass('procrastinate_jobs')")
        queue_schema_missing = cur.fetchone()[0] is None
        conn.execute(SCHEMA_SQL)
        conn.commit()
    if queue_schema_missing:
        connector = procrastinate.SyncPsycopgConnector(conninfo=dsn)
        with app.replace_connector(connector), app.open():
            app.schema_manager.apply_schema()


def _to_job(row: dict) -> dict:
    job = dict(row)
    job["job_id"] = job.pop("id")
    return job


def mark_running(dsn: str, job_id: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE sim_jobs SET status = 'running', started_at = now() WHERE id = %s",
            (job_id,),
        )
        conn.commit()


def mark_done(
    dsn: str,
    job_id: str,
    result: dict,
    artifacts: list | None = None,
    warning: str | None = None,
) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE sim_jobs SET status = 'done', result = %s, artifacts = %s, "
            "warning = %s, finished_at = now() WHERE id = %s",
            (
                Jsonb(result),
                Jsonb(artifacts) if artifacts is not None else None,
                warning,
                job_id,
            ),
        )
        conn.commit()


def mark_failed(dsn: str, job_id: str, error: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE sim_jobs SET status = 'failed', error = %s, finished_at = now() "
            "WHERE id = %s",
            (error, job_id),
        )
        conn.commit()


async def create_job(conn, job_id: str, job_type: str, params: dict) -> None:
    await conn.execute(
        "INSERT INTO sim_jobs (id, job_type, params, config_hash) "
        "VALUES (%s, %s, %s, %s)",
        (job_id, job_type, Jsonb(params), config_hash(params)),
    )


async def get_job(dsn: str, job_id: str) -> dict | None:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM sim_jobs WHERE id = %s", (job_id,)
        )
        row = await cur.fetchone()
    return _to_job(row) if row else None


async def list_recent(dsn: str, limit: int = 20) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM sim_jobs ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
    return [_to_job(row) for row in rows]
