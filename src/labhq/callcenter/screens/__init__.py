"""Read-only tmux screens for working agents and named private-server sessions (ADR 0004).

`ScreenReader` records when a running agent's screen changes for status freshness. It can
also list and capture any named session on labhq's private socket, including a dead pane.
It has no way to send keys: reading never disturbs an agent that works.
"""

from labhq.callcenter.screens.log import ScreenLog
from labhq.callcenter.screens.reader import (
    PaneSource,
    Screen,
    ScreenReader,
    default_screen_reader,
    running_tmux_run,
    screen_tail,
)

__all__ = [
    "PaneSource",
    "Screen",
    "ScreenLog",
    "ScreenReader",
    "default_screen_reader",
    "running_tmux_run",
    "screen_tail",
]
