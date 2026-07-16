"""The run_scenario tool: a named scenario across seeds with uncertainty."""
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server.mcp import mcp


async def test_run_scenario_aggregates_across_seeds():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "run_scenario",
            {"name": "A1_calm_baseline", "n_agents": 3000, "steps": 6, "seeds": 2},
        )
        r = result.data
        assert r["scenario"] == "A1_calm_baseline"
        assert r["family"] == "Market"
        assert r["question"]
        assert len(r["per_seed"]) == 2

        metrics = r["metrics"]
        for key in ("coverage", "precision", "final_trust", "retail_burn", "liquidated_frac"):
            assert key in metrics, f"missing {key}"
            assert "mean" in metrics[key] and "se" in metrics[key]

        per_seed_coverage = [row["coverage"] for row in r["per_seed"]]
        assert metrics["coverage"]["mean"] == pytest.approx(
            sum(per_seed_coverage) / len(per_seed_coverage)
        )


async def test_run_scenario_single_seed_has_no_standard_error():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "run_scenario",
            {"name": "A1_calm_baseline", "n_agents": 2000, "steps": 5, "seeds": 1},
        )
        assert result.data["metrics"]["coverage"]["se"] is None


async def test_run_scenario_rejects_unknown_name_and_lists_options():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="A1_calm_baseline"):
            await client.call_tool("run_scenario", {"name": "not_a_scenario"})


async def test_run_scenario_rejects_too_many_seeds():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="8"):
            await client.call_tool(
                "run_scenario", {"name": "A1_calm_baseline", "seeds": 9}
            )
