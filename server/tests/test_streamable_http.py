"""End-to-end: a real MCP client over Streamable HTTP against the served app."""
import socket
import threading
import time

import pytest
import uvicorn
from fastmcp import Client

from dfl24sim_server.app import create_app


@pytest.fixture
def mcp_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start within 10s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp/"
    server.should_exit = True
    thread.join(timeout=5)


async def test_list_scenarios_over_streamable_http(mcp_url):
    async with Client(mcp_url) as client:
        tools = await client.list_tools()
        assert "list_scenarios" in [t.name for t in tools]
        result = await client.call_tool("list_scenarios", {})
        assert len(result.data) == 12
