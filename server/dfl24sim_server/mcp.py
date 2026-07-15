"""The DFL24-Sim MCP server: tools a policy analyst's LLM can call."""
from fastmcp import FastMCP

from dfl24sim import scenarios

mcp = FastMCP("DFL24-Sim")


@mcp.tool
def list_scenarios() -> list[dict]:
    """List the twelve named stress-test scenarios of the DFL24-Sim simulator.

    Each scenario configures a retail crypto market world (market regime,
    adversary campaign, social-engineering wave, or policy design) and carries
    the policy question it answers. Use the returned `name` to run a scenario.
    """
    return [
        {"name": name, "family": family, "question": question}
        for name, family, question in scenarios.list_scenarios()
    ]
