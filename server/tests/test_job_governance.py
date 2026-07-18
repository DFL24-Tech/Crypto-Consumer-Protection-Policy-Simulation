"""Org governance: per-org job quota and config-hash result dedup.

Each test authenticates as a distinct fake org (via the same RemoteAuthProvider
machinery as test_auth_tenancy.py) so quota/cache state from one test can
never leak into another, without relying on the test database being reset.
"""
import asyncio
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import db, jobs
from dfl24sim_server.app import create_app
from dfl24sim_server.mcp import ORG_JOB_QUOTA, _enqueue_job, mcp

from conftest import drain_worker
from test_auth_tenancy import TOKENS, _free_port, _running_app

FAST_CALIBRATION = {"n_agents": 300, "steps": 3, "iters": 2, "n_seeds": 1}


@pytest.fixture
def two_org_client_factory(job_db):
    """Yields a function minting a Client authenticated as a fresh, unique org."""
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    tokens = dict(TOKENS)
    orgs: dict[str, str] = {}

    def make_org() -> str:
        token = f"token-{uuid.uuid4()}"
        org_id = f"org-{uuid.uuid4()}"
        tokens[token] = {"client_id": token, "sub": token, "org_id": org_id, "scopes": []}
        orgs[token] = org_id
        return token

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    provider = RemoteAuthProvider(
        token_verifier=StaticTokenVerifier(tokens),
        authorization_servers=["https://auth.example.test"],
        base_url=base,
    )
    with _running_app(create_app(auth=provider), port):
        def client_for(token: str) -> Client:
            return Client(f"{base}/mcp", auth=token)
        yield make_org, client_for


async def test_third_concurrent_job_is_rejected_naming_the_active_jobs(
    two_org_client_factory,
):
    make_org, client_for = two_org_client_factory
    token = make_org()
    async with client_for(token) as client:
        first = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
        second = (
            await client.call_tool(
                "run_calibration", {**FAST_CALIBRATION, "seed": 1}
            )
        ).data
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "run_calibration", {**FAST_CALIBRATION, "seed": 2}
            )
    message = str(exc.value)
    assert "quota" in message.lower()
    assert first["job_id"] in message
    assert second["job_id"] in message


async def test_quota_is_isolated_per_org(two_org_client_factory, job_db):
    make_org, client_for = two_org_client_factory
    org_a_token, org_b_token = make_org(), make_org()

    async with client_for(org_a_token) as a:
        await a.call_tool("run_calibration", FAST_CALIBRATION)
        await a.call_tool("run_calibration", {**FAST_CALIBRATION, "seed": 1})
        with pytest.raises(ToolError, match="quota"):
            await a.call_tool("run_calibration", {**FAST_CALIBRATION, "seed": 2})

    # org B is unaffected by org A sitting at quota
    async with client_for(org_b_token) as b:
        r = (await b.call_tool("run_calibration", FAST_CALIBRATION)).data
        assert r["status"] == "queued"


async def test_completed_jobs_do_not_count_against_quota(
    two_org_client_factory, job_db
):
    make_org, client_for = two_org_client_factory
    token = make_org()
    async with client_for(token) as client:
        first = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
    await drain_worker(job_db)  # first is now done, freeing a quota slot

    async with client_for(token) as client:
        second = (
            await client.call_tool(
                "run_calibration", {**FAST_CALIBRATION, "seed": 1}
            )
        ).data
        third = (
            await client.call_tool(
                "run_calibration", {**FAST_CALIBRATION, "seed": 2}
            )
        ).data
    assert {second["status"], third["status"]} == {"queued"}
    assert first["job_id"] not in (second["job_id"], third["job_id"])


async def test_identical_params_return_the_cached_result_as_a_cache_hit(
    two_org_client_factory, job_db
):
    make_org, client_for = two_org_client_factory
    token = make_org()
    async with client_for(token) as client:
        first = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
        assert first["cache_hit"] is False
    await drain_worker(job_db)

    async with client_for(token) as client:
        second = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data

    assert second["cache_hit"] is True
    assert second["job_id"] == first["job_id"]
    assert second["status"] == "done"


async def test_force_bypasses_the_cache(two_org_client_factory, job_db):
    make_org, client_for = two_org_client_factory
    token = make_org()
    async with client_for(token) as client:
        first = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
    await drain_worker(job_db)

    async with client_for(token) as client:
        forced = (
            await client.call_tool(
                "run_calibration", {**FAST_CALIBRATION, "force": True}
            )
        ).data

    assert forced["cache_hit"] is False
    assert forced["job_id"] != first["job_id"]
    assert forced["status"] == "queued"


async def test_dedup_does_not_cross_organizations(two_org_client_factory, job_db):
    make_org, client_for = two_org_client_factory
    org_a_token, org_b_token = make_org(), make_org()

    async with client_for(org_a_token) as a:
        first = (await a.call_tool("run_calibration", FAST_CALIBRATION)).data
    await drain_worker(job_db)

    async with client_for(org_b_token) as b:
        second = (await b.call_tool("run_calibration", FAST_CALIBRATION)).data

    assert second["cache_hit"] is False
    assert second["job_id"] != first["job_id"]


async def test_a_dedup_hit_does_not_consume_quota(two_org_client_factory, job_db):
    """Reusing a completed job's cached result must not compete with the
    quota check for genuinely new active jobs."""
    make_org, client_for = two_org_client_factory
    token = make_org()
    async with client_for(token) as client:
        cached = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
    await drain_worker(job_db)

    async with client_for(token) as client:
        # fill the quota with two unrelated active jobs
        await client.call_tool("run_calibration", {**FAST_CALIBRATION, "seed": 10})
        await client.call_tool("run_calibration", {**FAST_CALIBRATION, "seed": 11})
        # re-asking the already-completed question still returns the cache hit
        hit = (await client.call_tool("run_calibration", FAST_CALIBRATION)).data
        assert hit["cache_hit"] is True
        assert hit["job_id"] == cached["job_id"]


async def test_concurrent_triggers_for_one_org_cannot_exceed_quota(job_db):
    """The quota check and the insert must be atomic per org.

    Fires more simultaneous triggers than the quota allows, from one org
    starting empty (the no-auth 'dev' org). If the check and the insert are
    not serialized, several triggers all read a below-quota count before any
    of them commits, and the org ends up over quota. Calls the enqueue funnel
    directly so the coroutines genuinely overlap on the database.
    """
    async def trigger(seed: int) -> str:
        params = {**FAST_CALIBRATION, "seed": seed}
        try:
            result = await _enqueue_job(
                "calibration", jobs.run_calibration_job, params
            )
            return result["status"]
        except ToolError:
            return "rejected"

    statuses = await asyncio.gather(*(trigger(seed) for seed in range(6)))

    assert statuses.count("queued") == ORG_JOB_QUOTA
    assert statuses.count("rejected") == 6 - ORG_JOB_QUOTA
    active = await db.list_active_jobs(job_db, db.DEV_ORG)
    assert len(active) == ORG_JOB_QUOTA
