"""FastAPI application factory: REST routes and the mounted MCP endpoint."""
from fastapi import FastAPI

from .mcp import mcp


def create_app() -> FastAPI:
    # path="/" because the ASGI app is mounted at /mcp; the MCP session manager
    # only initializes if its lifespan is passed to the outer app.
    mcp_app = mcp.http_app(path="/")
    app = FastAPI(title="DFL24-Sim Server", lifespan=mcp_app.lifespan)
    app.mount("/mcp", mcp_app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
