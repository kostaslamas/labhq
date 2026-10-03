"""How the end of a turn is seen, per `TurnEnd` kind. The detectors are a registry.

A process exit ends every turn, whatever the agent's own signal; these decide the rest.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from labhq.adapters.tmux.agents import AgentKind, TurnEnd


@dataclass
class Watch:
    """What the adapter has seen of the pane so far."""

    screen: str
    last_change_at: datetime
    # True once the screen changed after start, so quiescence never fires on a blank pane.
    changed: bool = False
    signal: str | None = None


Detector = Callable[[Watch, AgentKind, datetime, timedelta], bool]


def _signal(watch: Watch, kind: AgentKind, now: datetime, quiet: timedelta) -> bool:
    return watch.signal is not None


def _exit(watch: Watch, kind: AgentKind, now: datetime, quiet: timedelta) -> bool:
    # The pane's death is checked by the adapter for every kind.
    return False


def _pattern(watch: Watch, kind: AgentKind, now: datetime, quiet: timedelta) -> bool:
    return kind.turn_end_pattern is not None and bool(
        re.search(kind.turn_end_pattern, watch.screen, re.MULTILINE)
    )


def quiescent(watch: Watch, now: datetime, quiet: timedelta) -> bool:
    return watch.changed and now - watch.last_change_at >= quiet


def _quiescence(watch: Watch, kind: AgentKind, now: datetime, quiet: timedelta) -> bool:
    return quiescent(watch, now, quiet)


DETECTORS: dict[TurnEnd, Detector] = {
    TurnEnd.SIGNAL: _signal,
    TurnEnd.EXIT: _exit,
    TurnEnd.PATTERN: _pattern,
    TurnEnd.QUIESCENCE: _quiescence,
}


def turn_ended(watch: Watch, kind: AgentKind, now: datetime, quiet: timedelta) -> bool:
    return DETECTORS[kind.turn_end](watch, kind, now, quiet)


def screen_delta(before: str, after: str) -> list[str]:
    """Lines of `after` that are new or differ from the same line of `before`."""
    old = before.splitlines()
    return [
        line
        for index, line in enumerate(after.splitlines())
        if index >= len(old) or old[index] != line
    ]
