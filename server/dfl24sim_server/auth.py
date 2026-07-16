"""Authentication and tenancy: WorkOS AuthKit in production, no-auth in dev.

Modes, selected by environment:

- ``DFL24_AUTHKIT_DOMAIN`` set — the MCP OAuth 2.1 flow via WorkOS AuthKit.
  Unauthenticated requests are rejected with 401 plus protected-resource
  metadata (so Claude/ChatGPT connector UIs can discover the flow), and
  bearer JWTs are verified against the AuthKit JWKS. Also requires
  ``DFL24_SERVER_BASE_URL``: the public URL clients reach this server on,
  which OAuth resource metadata must name.

- unset — no-auth dev mode: the compose and test workflow of earlier slices
  works without any WorkOS credentials, and every caller belongs to the
  ``dev`` organization.

Every job row is stamped with the caller's organization at enqueue time, and
job reads are scoped to it: another org's jobs are indistinguishable from
nonexistent ones.
"""
import os

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.server.dependencies import get_access_token

from .db import DEV_ORG


def build_auth_provider() -> AuthProvider | None:
    """The environment-selected auth mode (None = no-auth dev mode)."""
    domain = os.environ.get("DFL24_AUTHKIT_DOMAIN")
    if not domain:
        return None
    base_url = os.environ.get("DFL24_SERVER_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "DFL24_AUTHKIT_DOMAIN is set but DFL24_SERVER_BASE_URL is not; "
            "OAuth resource metadata must name the server's public URL."
        )
    from fastmcp.server.auth.providers.workos import AuthKitProvider

    return AuthKitProvider(authkit_domain=domain, base_url=base_url)


def caller_org() -> str:
    """The verified organization of the current request ('dev' when auth is off)."""
    token = get_access_token()
    if token is None:
        return DEV_ORG
    org = (token.claims or {}).get("org_id")
    if not org:
        raise ToolError(
            "Your token carries no organization (org_id claim); sign in "
            "through an organization to use this server."
        )
    return org
