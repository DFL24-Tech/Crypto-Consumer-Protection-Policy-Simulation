"""Shared fixtures: a real Postgres for the job-pipeline tests.

Uses DFL24_TEST_DATABASE_URL when set (CI service container); otherwise boots a
throwaway dockerized Postgres for the session.
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


@pytest.fixture()
def job_db(pg_dsn, monkeypatch):
    """Schema-applied database, wired into the server's runtime DSN."""
    from dfl24sim_server import db

    monkeypatch.setenv("DFL24_DATABASE_URL", pg_dsn)
    db.apply_schema(pg_dsn)
    yield pg_dsn


async def drain_worker(dsn: str) -> None:
    """Run a real worker against the test database until the queue is empty."""
    import procrastinate

    from dfl24sim_server import jobs

    connector = procrastinate.PsycopgConnector(conninfo=dsn)
    with jobs.app.replace_connector(connector):
        async with jobs.app.open_async():
            await jobs.app.run_worker_async(wait=False)
