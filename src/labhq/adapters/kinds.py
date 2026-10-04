"""The agents a person can pick by name: the SDK's Claude Code and every tmux agent kind.

An agent row stores an adapter key and a config; a kind is the name that fills both in, so
the CLI and the web app list the same registry instead of each knowing the JSON by heart.
A new tmux kind appears here by its own `register` call; nothing in this module changes.
"""

import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from labhq.adapters.claude import default_cli_path
from labhq.adapters.registry import UnknownAdapterError
from labhq.adapters.tmux.agents import AgentKinds, default_kinds
from labhq.settings import get_settings

TMUX_ADAPTER = "tmux"
SDK_CLAUDE = "claude"

Locate = Callable[[], str | None]


class UnknownAgentChoiceError(UnknownAdapterError):
    pass


@dataclass(frozen=True)
class AgentChoice:
    name: str
    adapter: str
    display_name: str
    # The program the agent needs on this machine.
    binary: str
    # The adapter's own config keys that make this choice, merged under the caller's config.
    config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    locate: Locate | None = None

    def found(self, which: Callable[[str], str | None] = shutil.which) -> str | None:
        """Where the binary is on this machine, or None."""
        if self.locate is not None:
            return self.locate()
        return which(self.binary)


def _claude_binary() -> str | None:
    # Runs pin the configured binary when there is one (`cli_path`), else the one on PATH.
    path: Path | None = default_cli_path(get_settings().cli_path)
    return str(path) if path is not None else None


CLAUDE_SDK = AgentChoice(
    name=SDK_CLAUDE,
    adapter=SDK_CLAUDE,
    display_name="Claude Code (SDK)",
    binary="claude",
    locate=_claude_binary,
)


def tmux_choices(kinds: AgentKinds) -> list[AgentChoice]:
    return [
        AgentChoice(
            name=kind.name,
            adapter=TMUX_ADAPTER,
            display_name=kind.display_name or kind.name,
            binary=kind.start[0],
            config=MappingProxyType({"agent": kind.name}),
        )
        for kind in (kinds.get(name) for name in kinds.names())
    ]


def agent_choices(kinds: AgentKinds | None = None) -> list[AgentChoice]:
    return [CLAUDE_SDK, *tmux_choices(kinds or default_kinds)]


def choice_named(name: str, kinds: AgentKinds | None = None) -> AgentChoice:
    choices = agent_choices(kinds)
    for choice in choices:
        if choice.name == name:
            return choice
    valid = ", ".join(choice.name for choice in choices)
    raise UnknownAgentChoiceError(f"no agent kind {name!r}; valid kinds: {valid}")
