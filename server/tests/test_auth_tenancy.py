"""Org tenancy: verified identities scope jobs; unauthenticated calls are 401'd.

Runs against a real uvicorn server with a static token verifier standing in
for WorkOS AuthKit — same RemoteAuthProvider machinery, fake identities.
"""
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
}
FAST_CALIBRATION = {"n_agents": 300, "steps": 3, "iters": 2, "n_seeds": 1}


@pytest.fixture
def authed_url(job_db):
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    provider = RemoteAuthProvider(
        token_verifier=StaticTokenVerifier(TOKENS),
        authorization_servers=["https://auth.example.test"],
        base_url=base,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(auth=provider), host="127.0.0.1", port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start within 10s")
        time.sleep(0.05)
    yield f"{base}/mcp"
    server.should_exit = True
    thread.join(timeout=5)
    mcp.auth = None  # the module-global mcp must not leak auth across tests


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
