"""The desktop UI's HTTP API (FastAPI), served beside the MCP app by `labhq serve`."""

from labhq.api.app import create_app, create_server_app
from labhq.api.deps import Owner, ResolverRegistry, default_resolvers
from labhq.api.hooks import HookRegistry, default_hooks
from labhq.api.routes import RouterRegistry, default_routers

__all__ = [
    "HookRegistry",
    "Owner",
    "ResolverRegistry",
    "RouterRegistry",
    "create_app",
    "create_server_app",
    "default_hooks",
    "default_resolvers",
    "default_routers",
]
