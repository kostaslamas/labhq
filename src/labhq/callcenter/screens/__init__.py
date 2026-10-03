"""Reading a working agent's screen, read-only, when its status is stale (ADR 0004).

`ScreenReader` captures the pane of an agent's running tmux run and records when the
screen last changed, so an agent's last activity is the later of its latest `run_events`
row and its last screen change. It has no way to send keys: reading never disturbs the
agent that works.
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
