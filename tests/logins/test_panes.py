"""The login command runs in a real private tmux pane, and its link is read off the screen."""

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from labhq.adapters.tmux import TmuxServer
from labhq.clock import SystemClock
from labhq.logins import TmuxPanes, login_tools
from tests.adapters.tmux.conftest import require_tmux

URL = "https://auth.openai.com/oauth/authorize?state=" + "x" * 120
# A fake login command: prints a link longer than a line and waits, like a real one.
SCRIPT = f"import time; print('Open this link:'); print({URL!r}); time.sleep(30)"


@pytest.fixture
def panes(tmp_path: Path) -> Iterator[TmuxPanes]:
    binary = require_tmux()
    server = TmuxServer(
        socket=f"labhq-login-test-{uuid.uuid4().hex[:8]}",
        state_dir=tmp_path / "tmux",
        binary=binary,
    )
    try:
        yield TmuxPanes(server)
    finally:
        server.kill_server()


async def test_the_link_is_read_whole_from_a_real_pane_and_the_pane_is_killed(
    panes: TmuxPanes, tmp_path: Path
) -> None:
    panes.start("login-codex-1", (sys.executable, "-c", SCRIPT), tmp_path / "work")

    screen = ""
    for _ in range(100):
        screen = panes.screen("login-codex-1")
        if URL in screen:
            break
        await SystemClock().sleep(0.05)  # a real child process: the OS, not a fake clock

    assert login_tools.get("codex").find_url(screen) == URL
    assert panes.alive("login-codex-1")
    panes.kill("login-codex-1")
    assert not panes.alive("login-codex-1")
    assert panes.screen("login-codex-1") == ""
