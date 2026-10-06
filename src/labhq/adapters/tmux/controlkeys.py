"""Control keys the owner (or a manager) can send to a tmux agent, by name.

A name maps to a tmux key name. Anything else is refused: this path never types text.
"""

from dataclasses import dataclass

from labhq.adapters.tmux.agents import AgentKind


@dataclass(frozen=True)
class ControlKey:
    name: str
    tmux_key: str


CONTROL_KEYS: dict[str, ControlKey] = {
    key.name: key
    for key in (
        ControlKey("escape", "Escape"),
        ControlKey("shift_tab", "BTab"),
        ControlKey("ctrl_c", "C-c"),
    )
}


class ControlKeyRefusedError(ValueError):
    pass


def tmux_key(kind: AgentKind, name: str) -> str:
    """The tmux key for `name`, if the kind lists it."""
    key = CONTROL_KEYS.get(name)
    if key is None or name not in kind.control_keys:
        listed = ", ".join(kind.control_keys) or "none"
        raise ControlKeyRefusedError(
            f"{kind.display_name or kind.name} does not accept the key {name!r}; accepted: {listed}"
        )
    return key.tmux_key
