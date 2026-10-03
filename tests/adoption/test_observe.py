"""Outside tmux, the process table stands in for the screen; a quiet process ends the turn."""

import subprocess
import sys

import psutil

from labhq.adoption.observe import ProcessObserver, wait_for_turn_end
from tests.adoption.conftest import CLOCK


async def test_an_idle_process_has_ended_its_turn() -> None:
    with subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE) as process:
        try:
            started = psutil.Process(process.pid).create_time()
            observer = ProcessObserver(process.pid, started)

            seen = await wait_for_turn_end(observer, CLOCK, poll=0.05, quiet=0.3, timeout=10)

            assert seen.alive
            assert seen.screen is None
        finally:
            process.kill()


async def test_a_process_that_exits_has_ended_its_turn() -> None:
    with subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE) as process:
        started = psutil.Process(process.pid).create_time()
        process.kill()
        process.wait()

        seen = await wait_for_turn_end(
            ProcessObserver(process.pid, started), CLOCK, poll=0.05, quiet=5, timeout=10
        )

    assert not seen.alive
