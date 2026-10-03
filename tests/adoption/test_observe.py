"""Outside tmux, the process table stands in for the screen; a quiet process ends the turn."""

import shlex
import subprocess
import sys
from pathlib import Path

import psutil

from labhq.adoption.discovery import is_alive
from labhq.adoption.move import end_process
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


async def test_ending_an_agent_its_parent_never_reaps_returns_once_it_is_a_zombie(
    tmp_path: Path,
) -> None:
    # The agent is another process's child, as under the owner's shell or tmux: here a
    # parent that execs into `sleep` and never reaps it, so the ended agent stays a zombie.
    pidfile = tmp_path / "agent.pid"
    write_pid = f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))"
    agent = f"import os, signal; {write_pid}; signal.pause()"
    script = f"{shlex.quote(sys.executable)} -c {shlex.quote(agent)} & exec sleep 30"
    with subprocess.Popen(["/bin/sh", "-c", script]) as parent:
        try:
            for _ in range(200):
                if pidfile.exists() and pidfile.read_text():
                    break
                await CLOCK.sleep(0.05)
            pid = int(pidfile.read_text())
            started = psutil.Process(pid).create_time()

            end_process(pid, started, timeout=2)

            assert not is_alive(pid, started)
        finally:
            parent.kill()
