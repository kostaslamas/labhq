"""Output style per recipient: one short instruction appended to a role's system prompt.

Whatever an agent writes for another agent is read again as that agent's input, so a terse
style saves twice (plan §7.1). The instruction shapes prose only; it never asks the model to
think less or to shorten code.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# The key in `agents.config` that names who reads the agent's output.
RECIPIENT_CONFIG_KEY = "output_recipient"
DEFAULT_RECIPIENT = "agent"

_SCOPE = (
    "This limits prose only: reason as fully as the task needs, and never shorten code, "
    "commands, paths, identifiers or error text."
)

# Not prose style: it tells a working agent where to report, so the owner is not interrupted.
STATUS_INSTRUCTION = (
    "Keep .labhq/status.md current (summary, done, next, blockers, refs) and put every "
    "question for the owner under its questions field, one per line; never wait on a reply."
)

AGENT_STYLE = (
    "Output style: terse. Your reader is another agent. Lead with the result. Fragments are "
    "fine; no greetings, filler, hedging or restating the request. "
    + _SCOPE
    + " "
    + STATUS_INSTRUCTION
)

USER_STYLE = (
    "Output style: natural. Your reader is the person who owns this project. Write clear, "
    "complete sentences in plain words and lead with what matters to them. "
    + _SCOPE
    + " "
    + STATUS_INSTRUCTION
)


class UnknownRecipientError(LookupError):
    pass


class DuplicateRecipientError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OutputStyle:
    recipient: str
    instruction: str


class StyleRegistry:
    """Maps a recipient to its style. A new recipient is a new registration."""

    def __init__(self) -> None:
        self._styles: dict[str, OutputStyle] = {}

    def register(self, recipient: str, instruction: str, *, replace: bool = False) -> None:
        if not recipient or not instruction.strip():
            raise ValueError("a style needs a recipient and a non-empty instruction")
        if recipient in self._styles and not replace:
            raise DuplicateRecipientError(recipient)
        self._styles[recipient] = OutputStyle(recipient, instruction.strip())

    def get(self, recipient: str) -> OutputStyle:
        try:
            return self._styles[recipient]
        except KeyError:
            raise UnknownRecipientError(recipient) from None

    def recipients(self) -> frozenset[str]:
        return frozenset(self._styles)


def default_registry() -> StyleRegistry:
    registry = StyleRegistry()
    registry.register("agent", AGENT_STYLE)
    registry.register("user", USER_STYLE)
    return registry


def recipient_from_config(agent_config: Mapping[str, Any]) -> str:
    recipient = agent_config.get(RECIPIENT_CONFIG_KEY, DEFAULT_RECIPIENT)
    if not isinstance(recipient, str) or not recipient:
        raise ValueError(f"{RECIPIENT_CONFIG_KEY} must be a non-empty string: {recipient!r}")
    return recipient


def styled_system_prompt(
    system_prompt: str, agent_config: Mapping[str, Any], registry: StyleRegistry
) -> str:
    """Append the style for the recipient named in `agent_config` to the role's prompt."""
    style = registry.get(recipient_from_config(agent_config))
    if not system_prompt.strip():
        return style.instruction
    return f"{system_prompt.rstrip()}\n\n{style.instruction}"
