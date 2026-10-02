"""MCP server (Streamable HTTP, stateless, JSON) behind the bearer guard."""

import os
import secrets
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp

from mcp_auth.auth import BearerAuthMiddleware

TOKEN_ENV = "LABHQ_SPIKE_TOKEN"


def build_mcp() -> MCPServer:
    mcp = MCPServer("labhq-spike")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def what_time_is_it() -> str:
        """Return the current UTC time and a sentence that is fine to read aloud."""
        now = datetime.now(UTC)
        return (
            f"{now.isoformat(timespec='seconds')} "
            f"It is {now:%H:%M} UTC; the connection to the call center works."
        )

    return mcp


def build_app(token: str) -> ASGIApp:
    # Stateless + JSON: no session affinity and no SSE, which Cloudflare quick
    # tunnels cannot carry. Host-header (DNS rebinding) checks are off because
    # tunnel hostnames are unknowable up front; the bearer guard covers the
    # threat they address.
    mcp_app = build_mcp().streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerAuthMiddleware(mcp_app, token)


def resolve_token() -> tuple[str, bool]:
    """Return (token, generated)."""
    configured = os.environ.get(TOKEN_ENV)
    if configured:
        return configured, False
    return secrets.token_urlsafe(32), True
