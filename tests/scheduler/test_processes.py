"""Process termination: the POSIX process-group terminator and the platform registry."""

import os
import signal
import subprocess
import sys

import psutil
import pytest

from labhq.scheduler import (
    PosixProcessGroupTerminator,
    UnsupportedPlatformError,
    register_terminator,
    terminator_for,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")

# The leader starts a child, reports its pid, then waits on it: a two-level process tree.
_LEADER = (
    "import subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],"
    " stdin=subprocess.PIPE)\n"
    "print(child.pid, flush=True)\n"
    "child.wait()\n"
)


def _group_leader() -> tuple[subprocess.Popen[str], psutil.Process]:
    leader = subprocess.Popen(
        [sys.executable, "-c", _LEADER],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert leader.stdout is not None
    child = psutil.Process(int(leader.stdout.readline()))
    return leader, child


@posix_only
@pytest.mark.parametrize(
    ("method", "signum"),
    [("terminate", signal.SIGTERM), ("kill", signal.SIGKILL)],
)
def test_posix_terminator_signals_the_whole_process_group(method: str, signum: int) -> None:
    leader, child = _group_leader()
    group = os.getpgid(leader.pid)
    try:
        getattr(PosixProcessGroupTerminator(), method)(leader.pid)

        assert leader.wait(timeout=10) == -signum
        _, alive = psutil.wait_procs([child], timeout=10)
        # An orphan that awaits its reaper is dead already.
        assert all(proc.status() == psutil.STATUS_ZOMBIE for proc in alive)
    finally:
        if leader.poll() is None:
            os.killpg(group, signal.SIGKILL)
        with leader:
            leader.wait()


@posix_only
def test_posix_terminator_ignores_a_process_that_is_already_gone() -> None:
    leader, child = _group_leader()
    os.killpg(os.getpgid(leader.pid), signal.SIGKILL)
    with leader:
        leader.wait()
    psutil.wait_procs([child], timeout=10)

    PosixProcessGroupTerminator().terminate(leader.pid)


def test_the_registry_answers_posix_and_refuses_an_unknown_platform() -> None:
    assert isinstance(terminator_for("posix"), PosixProcessGroupTerminator)
    with pytest.raises(UnsupportedPlatformError):
        terminator_for("plan9")
    with pytest.raises(ValueError, match="already registered"):
        register_terminator("posix", PosixProcessGroupTerminator)
