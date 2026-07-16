"""ASGI application factory: the FastMCP HTTP app plus public REST routes.

The FastMCP app is served at the root (MCP endpoint on /mcp) rather than
mounted into an outer app: the OAuth protected-resource metadata must live at
/.well-known/oauth-protected-resource/mcp on the server root (RFC 9728), and
FastMCP registers it there itself. REST routes like /health ride along as
custom routes, outside the auth gate.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import build_auth_provider
from .mcp import mcp


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(auth=None):
    # auth resolves at app-build time, not import time, so tests can inject a
    # provider and deployments pick up the environment (see auth.py for modes)
    mcp.auth = auth if auth is not None else build_auth_provider()
    return mcp.http_app(path="/mcp")
