"""The private tmux pane a tool's login command runs in.

The contract has no way to send a key: a code the tool asks for is pasted by the owner in
the terminal, never relayed through labhq.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from labhq.adapters.tmux.server import TmuxError, TmuxServer

PANE_PREFIX = "login"


class LoginPanes(Protocol):
    socket: str

    def start(self, name: str, argv: Sequence[str], cwd: Path) -> None: ...

    def screen(self, name: str) -> str: ...

    def alive(self, name: str) -> bool: ...

    def kill(self, name: str) -> None: ...


def pane_name(tool: str, account: str, request_id: int) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", f"{tool}-{account}")
    return f"{PANE_PREFIX}-{safe}-{request_id}"


class TmuxPanes:
    def __init__(self, server: TmuxServer) -> None:
        self._server = server
        self.socket = server.socket

    def start(self, name: str, argv: Sequence[str], cwd: Path) -> None:
        cwd.mkdir(parents=True, exist_ok=True)
        self._server.new_session(name, cwd=cwd, argv=argv, variables={})

    def screen(self, name: str) -> str:
        try:
            return self._server.capture(name)
        except TmuxError:
            return ""

    def alive(self, name: str) -> bool:
        try:
            return self._server.has_session(name) and not self._server.pane_state(name).dead
        except TmuxError:
            return False

    def kill(self, name: str) -> None:
        try:
            self._server.kill_session(name)
        except TmuxError:
            return
