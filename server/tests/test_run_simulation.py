"""The run_simulation tool: one capped, seeded simulation returning headline numbers."""
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server.mcp import mcp


async def test_run_simulation_returns_headline_summary():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "run_simulation", {"n_agents": 3000, "steps": 6, "seed": 0}
        )
        s = result.data
        assert s["n_agents"] == 3000
        assert s["steps"] == 6
        for key in (
            "friction_precision",
            "adversary_detection",
            "detection_by_role",
            "final_trust",
            "liquidated_frac",
            "scam_victim_frac",
            "false_positive_count",
            "final_price",
            "max_price",
            "min_price",
        ):
            assert key in s, f"missing {key}"
        assert 0.0 <= s["final_trust"] <= 1.0


async def test_run_simulation_is_reproducible_for_a_seed():
    async with Client(mcp) as client:
        args = {"n_agents": 2000, "steps": 5, "seed": 7}
        first = (await client.call_tool("run_simulation", args)).data
        second = (await client.call_tool("run_simulation", args)).data
        assert first == second


async def test_run_simulation_policy_toggles_change_outcomes():
    async with Client(mcp) as client:
        base = {"n_agents": 3000, "steps": 6, "seed": 0}
        on = (await client.call_tool("run_simulation", base)).data
        off = (
            await client.call_tool(
                "run_simulation", {**base, "friction_off": True, "policy_off": True}
            )
        ).data
        # with compliance off nothing is ever flagged
        assert off["adversary_detection"] == 0.0
        assert on["adversary_detection"] != off["adversary_detection"]


@pytest.mark.parametrize(
    "args, cap_text",
    [
        ({"n_agents": 500_000}, "100000"),
        ({"n_agents": 2000, "steps": 500}, "60"),
    ],
)
async def test_run_simulation_rejects_over_cap_inputs(args, cap_text):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match=cap_text):
            await client.call_tool("run_simulation", args)


@pytest.mark.parametrize(
    "args",
    [
        {"n_agents": 0},
        {"n_agents": 2000, "steps": 0},
        {"n_agents": -5},
    ],
)
async def test_run_simulation_rejects_non_positive_inputs(args):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="at least 1"):
            await client.call_tool("run_simulation", args)
