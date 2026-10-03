"""Tool specs as data: a new tool is a new registration, never a server edit."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

from mcp.types import ToolAnnotations

# A handler may take typed keyword arguments (the SDK derives the input schema from them)
# and always returns the sentence to read aloud.
ToolHandler = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    # The description carries the rules for the calling model (plan §3.2 rule 5).
    description: str
    annotations: ToolAnnotations
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool {spec.name!r} is already registered.")
        self._specs[spec.name] = spec

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)


default_registry = ToolRegistry()
