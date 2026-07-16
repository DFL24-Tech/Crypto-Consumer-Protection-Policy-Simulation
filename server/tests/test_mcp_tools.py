"""MCP tool behavior, exercised through a real MCP client (in-memory transport)."""
from fastmcp import Client

from dfl24sim_server.mcp import mcp


async def test_list_scenarios_is_advertised():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert "list_scenarios" in [t.name for t in tools]


async def test_list_scenarios_returns_all_twelve_with_descriptions():
    async with Client(mcp) as client:
        result = await client.call_tool("list_scenarios", {})
        scenarios = result.data
        assert len(scenarios) == 12
        names = {s["name"] for s in scenarios}
        assert "A1_calm_baseline" in names
        assert "C1_pig_butchering_wave" in names
        for s in scenarios:
            assert s["name"]
            assert s["family"] in {"Market", "Adversary", "Social-eng", "Policy"}
            assert s["question"]
