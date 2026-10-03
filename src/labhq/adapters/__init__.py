"""Agent adapters and the registry that names them.

`default_registry` carries the built-in adapters. Another adapter joins with one
`register` call; nothing that dispatches on the key changes.
"""

from labhq.adapters.base import (
    Adapter,
    AdapterError,
    AdapterEvent,
    AdapterResult,
    AgentTool,
    RunRequest,
)
from labhq.adapters.claude import ClaudeAdapter, default_cli_path
from labhq.adapters.fake import FakeAdapter, FakeScript
from labhq.adapters.registry import AdapterFactory, AdapterRegistry, UnknownAdapterError
from labhq.settings import get_settings


def _claude() -> Adapter:
    return ClaudeAdapter(cli_path=default_cli_path(get_settings().cli_path))


default_registry = AdapterRegistry()
default_registry.register("fake", FakeAdapter)
default_registry.register("claude", _claude)

__all__ = [
    "Adapter",
    "AdapterError",
    "AdapterEvent",
    "AdapterFactory",
    "AdapterRegistry",
    "AdapterResult",
    "AgentTool",
    "ClaudeAdapter",
    "FakeAdapter",
    "FakeScript",
    "RunRequest",
    "UnknownAdapterError",
    "default_registry",
]
