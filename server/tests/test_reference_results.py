"""get_reference_results: precomputed results/ numbers served with provenance.

These tests run without a database or queue on purpose: the reference bundle
is read-only data shipped with the server package.
"""
import importlib.util
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dfl24sim_server import reference
from dfl24sim_server.mcp import mcp

TOPICS = {"calibration", "sensitivity", "coverage", "fade", "battery", "validation"}


def test_bundle_is_in_sync_with_results_artifacts():
    """A regenerated results/ requires rerunning build_reference_data.py."""
    script = Path(__file__).parents[1] / "scripts" / "build_reference_data.py"
    spec = importlib.util.spec_from_file_location("build_reference_data", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build() == reference._DATA


async def test_tool_is_advertised_with_simulation_caveat_in_description():
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert "get_reference_results" in tools
        # the LLM only ever sees the description: the framing must live there
        assert "not field measurements" in tools["get_reference_results"].description


async def test_no_topic_lists_supported_topics():
    async with Client(mcp) as client:
        result = await client.call_tool("get_reference_results", {})
        assert set(result.data["supported_topics"]) == TOPICS


async def test_every_topic_carries_provenance_and_caveat():
    async with Client(mcp) as client:
        for topic in TOPICS:
            data = (await client.call_tool(
                "get_reference_results", {"topic": topic}
            )).data
            assert data["topic"] == topic
            assert data["headline"]
            assert data["numbers"]
            prov = data["provenance"]
            assert "White paper" in prov["whitepaper_section"]
            assert prov["source_files"]
            assert all(f.startswith("results/") for f in prov["source_files"])
            assert "simulation" in data["caveat"]
            assert "not field measurements" in data["caveat"]


async def test_calibration_serves_the_headline_effect_size():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "calibration"}
        )).data["numbers"]
        assert n["converged"] is True
        assert n["achieved_moments"]["first_reduction"] == pytest.approx(0.1432, abs=1e-3)
        assert n["targets"]["first_reduction"] == pytest.approx(0.095)
        assert n["estimated"]["fric_attention"] == pytest.approx(1.1298, abs=1e-3)


async def test_coverage_serves_static_and_adaptive_rates_per_role():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "coverage"}
        )).data["numbers"]
        assert n["static"]["sybil_attacker"]["rate"] == pytest.approx(1.0)
        assert n["static"]["cyber_red_team"]["rate"] == pytest.approx(0.0)
        # the adaptive collapse: sybil detection falls from 100% to ~12%
        assert n["adaptive"]["sybil_attacker"]["rate"] == pytest.approx(0.117, abs=1e-2)
        assert n["adaptive"]["market_manipulator"]["rate"] == pytest.approx(0.187, abs=1e-2)


async def test_fade_serves_the_per_step_reduction_series():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "fade"}
        )).data["numbers"]
        series = n["per_step"]
        assert len(series) == 14
        assert series[0]["reduction"] == pytest.approx(0.1297, abs=1e-3)
        # the effect fades: late-horizon reduction sits below first exposure
        assert series[-1]["reduction"] < series[0]["reduction"]
        assert n["fade_ratio"]["achieved"] == pytest.approx(0.558, abs=1e-2)


async def test_battery_serves_all_twenty_policy_attack_cells():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "battery"}
        )).data["numbers"]
        rows = n["battery"]
        assert len(rows) == 20
        by_cell = {(r["policy"], r["attack"]): r for r in rows}
        std = by_cell[("standard", "pump_dump")]
        over = by_cell[("over_friction", "pump_dump")]
        # over-friction is dominated: same coverage, destroyed trust
        assert over["coverage"] == pytest.approx(std["coverage"], abs=0.01)
        assert over["final_trust"] < std["final_trust"] - 0.05


async def test_sensitivity_serves_sobol_and_morris_drivers():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "sensitivity"}
        )).data["numbers"]
        sybil = n["sobol"]["sybil_coverage"]
        assert sybil["names"][sybil["S1"].index(max(sybil["S1"]))] == "epsilon"
        assert max(sybil["S1"]) == pytest.approx(0.963, abs=1e-2)
        trust = n["sobol"]["final_trust"]
        assert trust["names"][trust["S1"].index(max(trust["S1"]))] == "theta_fa"
        assert "first_reduction" in n["morris"]


async def test_validation_serves_stylized_facts_and_convergence():
    async with Client(mcp) as client:
        n = (await client.call_tool(
            "get_reference_results", {"topic": "validation"}
        )).data["numbers"]
        assert n["stylized_calm"]["excess_kurtosis"] == pytest.approx(46.7, abs=0.1)
        assert n["convergence"]["first_reduction"]["mean"] == pytest.approx(0.1287, abs=1e-3)
        assert n["convergence"]["coverage"]["se"] < 0.001


async def test_unknown_topic_reports_the_supported_topics():
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool("get_reference_results", {"topic": "vibes"})
        for topic in TOPICS:
            assert topic in str(exc.value)
