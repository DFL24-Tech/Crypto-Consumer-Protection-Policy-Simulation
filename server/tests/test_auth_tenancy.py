"""Org tenancy: verified identities scope jobs; unauthenticated calls are 401'd.

Runs against a real uvicorn server with a static token verifier standing in
for WorkOS AuthKit — same RemoteAuthProvider machinery, fake identities.
"""
import contextlib
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db
from dfl24sim_server.app import create_app
from dfl24sim_server.mcp import mcp

TOKENS = {
    "token-alice": {"client_id": "alice", "sub": "user-alice",
                    "org_id": "org-a", "scopes": []},
    "token-bob": {"client_id": "bob", "sub": "user-bob",
                  "org_id": "org-b", "scopes": []},
    "token-no-org": {"client_id": "carol", "sub": "user-carol", "scopes": []},
}
FAST_CALIBRATION = {"n_agents": 300, "steps": 3, "iters": 2, "n_seeds": 1}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _running_app(app, port: int, *, startup_timeout: float = 10.0):
    """Boots an ASGI app on 127.0.0.1:port; always resets mcp.auth on exit.

    A plain context manager, not the pytest fixture itself, so the
    reset-on-failure guarantee is directly testable without pytest's fixture
    machinery standing in the way — the module-global `mcp` singleton must
    not leak a test's auth provider into whatever test runs next, even if
    the server never finishes starting.
    """
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + startup_timeout
        while not server.started:
            if time.time() > deadline:
                raise RuntimeError(f"uvicorn did not start within {startup_timeout}s")
            time.sleep(0.05)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        mcp.auth = None


@pytest.fixture
def authed_url(job_db):
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    provider = RemoteAuthProvider(
        token_verifier=StaticTokenVerifier(TOKENS),
        authorization_servers=["https://auth.example.test"],
        base_url=base,
    )
    with _running_app(create_app(auth=provider), port):
        yield f"{base}/mcp"


async def test_jobs_are_stamped_and_scoped_by_the_callers_org(authed_url, job_db):
    async with Client(authed_url, auth="token-alice") as alice:
        job_id = (
            await alice.call_tool("run_calibration", FAST_CALIBRATION)
        ).data["job_id"]
        status = (await alice.call_tool("get_job_status", {"job_id": job_id})).data
        assert status["status"] == "queued"
        recent = (await alice.call_tool("get_job_status", {})).data["recent"]
        assert job_id in {j["job_id"] for j in recent}

    assert (await db.get_job(job_db, job_id))["org_id"] == "org-a"

    # bob's organization sees nothing of alice's job, same as an unknown id
    async with Client(authed_url, auth="token-bob") as bob:
        for tool, args in [
            ("get_job_status", {"job_id": job_id}),
            ("get_job_result", {"job_id": job_id}),
            ("get_artifact", {"job_id": job_id}),
        ]:
            with pytest.raises(ToolError, match="No job"):
                await bob.call_tool(tool, args)
        recent = (await bob.call_tool("get_job_status", {})).data["recent"]
        assert job_id not in {j["job_id"] for j in recent}


async def test_unauthenticated_requests_get_401_with_resource_metadata(authed_url):
    response = httpx.post(
        authed_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert "resource_metadata=" in challenge

    metadata_url = challenge.split('resource_metadata="')[1].split('"')[0]
    metadata = httpx.get(metadata_url).json()
    assert "https://auth.example.test" in metadata["authorization_servers"][0]


async def test_no_auth_mode_stamps_the_dev_org(job_db):
    async with Client(mcp) as client:
        job_id = (
            await client.call_tool("run_calibration", FAST_CALIBRATION)
        ).data["job_id"]

    assert (await db.get_job(job_db, job_id))["org_id"] == "dev"


async def test_token_without_org_claim_is_rejected(authed_url):
    async with Client(authed_url, auth="token-no-org") as carol:
        with pytest.raises(ToolError, match="organization"):
            await carol.call_tool("run_calibration", FAST_CALIBRATION)


def test_running_app_resets_auth_even_when_startup_never_completes(monkeypatch):
    """Regression for a leak: mcp.auth must reset even if the server never
    reports started, not just on the happy path (see _running_app's docstring).

    Patches uvicorn.Server.run to never flip `started`, rather than racing a
    real server against a short timeout, so the failure path fires every time.
    """
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    def _never_starts(self, sockets=None) -> None:
        while not self.should_exit:
            time.sleep(0.02)

    monkeypatch.setattr(uvicorn.Server, "run", _never_starts)

    port = _free_port()
    provider = RemoteAuthProvider(
        token_verifier=StaticTokenVerifier(TOKENS),
        authorization_servers=["https://auth.example.test"],
        base_url=f"http://127.0.0.1:{port}",
    )
    app = create_app(auth=provider)
    assert mcp.auth is provider  # sanity: create_app did mutate the singleton

    with pytest.raises(RuntimeError, match="did not start"):
        with _running_app(app, port, startup_timeout=0.2):
            pytest.fail("must never reach the body: the server never starts")

    assert mcp.auth is None
