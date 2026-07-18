"""Shared fixtures: a real Postgres and a real MinIO for the pipeline tests.

Uses DFL24_TEST_DATABASE_URL / DFL24_TEST_S3_URL when set (CI service
containers); otherwise boots throwaway dockerized services for the session.
"""
import os
import socket
import subprocess
import time

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_dsn():
    provided = os.environ.get("DFL24_TEST_DATABASE_URL")
    if provided:
        yield provided
        return

    import psycopg

    port = _free_port()
    name = f"dfl24-test-pg-{port}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-e", "POSTGRES_USER=dfl24", "-e", "POSTGRES_PASSWORD=dfl24",
         "-e", "POSTGRES_DB=dfl24sim", "-p", f"{port}:5432", "postgres:16-alpine"],
        check=True, capture_output=True,
    )
    dsn = f"postgresql://dfl24:dfl24@127.0.0.1:{port}/dfl24sim"
    try:
        deadline = time.time() + 60
        while True:
            try:
                psycopg.connect(dsn, connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                if time.time() > deadline:
                    raise RuntimeError("test postgres did not become ready in 60s")
                time.sleep(0.5)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


S3_USER = "dfl24"
S3_PASSWORD = "dfl24secret"  # MinIO requires >= 8 chars


@pytest.fixture(scope="session")
def s3_url():
    provided = os.environ.get("DFL24_TEST_S3_URL")
    if provided:
        yield provided
        return

    import httpx

    port = _free_port()
    name = f"dfl24-test-minio-{port}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-e", f"MINIO_ROOT_USER={S3_USER}",
         "-e", f"MINIO_ROOT_PASSWORD={S3_PASSWORD}",
         "-p", f"{port}:9000", "minio/minio", "server", "/data"],
        check=True, capture_output=True,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while True:
            try:
                httpx.get(f"{url}/minio/health/live").raise_for_status()
                break
            except Exception:
                if time.time() > deadline:
                    raise RuntimeError("test minio did not become ready in 60s")
                time.sleep(0.5)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture()
def artifact_store(s3_url, monkeypatch):
    """Object storage wired into the server's runtime configuration."""
    monkeypatch.setenv("DFL24_S3_ENDPOINT", s3_url)
    monkeypatch.setenv("DFL24_S3_ACCESS_KEY", S3_USER)
    monkeypatch.setenv("DFL24_S3_SECRET_KEY", S3_PASSWORD)
    monkeypatch.setenv("DFL24_S3_BUCKET", "dfl24-artifacts")
    yield s3_url


@pytest.fixture()
def job_db(pg_dsn, monkeypatch):
    """Schema-applied, emptied database, wired into the server's runtime DSN.

    The underlying Postgres is session-scoped (booting it per test would be
    slow), so each test truncates the job tables itself. This also matters
    now that jobs carry per-org quota/dedup state (see mcp.py): without a
    clean slate, jobs left behind by an earlier test in the shared no-auth
    "dev" org would count against this test's quota or dedup its results.
    """
    import psycopg

    from dfl24sim_server import db

    monkeypatch.setenv("DFL24_DATABASE_URL", pg_dsn)
    db.apply_schema(pg_dsn)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "TRUNCATE TABLE sim_jobs, procrastinate_jobs, procrastinate_events, "
            "procrastinate_periodic_defers, procrastinate_workers "
            "RESTART IDENTITY CASCADE"
        )
        conn.commit()
    yield pg_dsn


async def drain_worker(dsn: str) -> None:
    """Run a real worker against the test database until the queue is empty."""
    import procrastinate

    from dfl24sim_server import jobs

    connector = procrastinate.PsycopgConnector(conninfo=dsn)
    with jobs.app.replace_connector(connector):
        async with jobs.app.open_async():
            await jobs.app.run_worker_async(wait=False)
