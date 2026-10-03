"""MCP server (Streamable HTTP, stateless, JSON) built from a tool registry."""

import functools
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from labhq.mcp.auth import BearerAuthMiddleware
from labhq.mcp.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)

SERVER_NAME = "labhq"


def _spoken_error(error: Exception) -> str:
    reason = " ".join(str(error).split()) or type(error).__name__
    return f"Sorry, that did not work: {reason[:120].rstrip('.')}."


def _guarded(spec: ToolSpec) -> Any:
    @functools.wraps(spec.handler)
    async def call(*args: Any, **kwargs: Any) -> str:
        try:
            return await spec.handler(*args, **kwargs)
        except Exception as error:
            # The traceback stays in the log; the caller hears one sentence.
            logger.exception("Tool %s failed", spec.name)
            return _spoken_error(error)

    return call


def build_mcp(registry: ToolRegistry) -> MCPServer:
    server = MCPServer(SERVER_NAME)
    for spec in registry:
        server.add_tool(
            _guarded(spec),
            name=spec.name,
            description=spec.description,
            annotations=spec.annotations,
        )
    return server


def build_app(registry: ToolRegistry, token: str) -> ASGIApp:
    # Stateless + JSON: no session affinity and no SSE, which Cloudflare quick tunnels cannot
    # carry. Host-header (DNS rebinding) checks are off because tunnel hostnames are unknowable
    # up front; the token covers the threat they address.
    mcp_app = build_mcp(registry).streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerAuthMiddleware(mcp_app, token)
