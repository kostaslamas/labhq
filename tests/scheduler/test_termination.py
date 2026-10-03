"""Process termination: a per-platform registry, POSIX signalling the whole group."""

import asyncio
import os
import signal
import subprocess
from collections.abc import Sequence

import pytest

from labhq.scheduler import (
    PosixProcessGroupTerminator,
    TerminatorRegistry,
    UnsupportedPlatformError,
    WindowsTaskkillTerminator,
    default_terminators,
)
from labhq.scheduler.termination import CREATE_NEW_PROCESS_GROUP


async def _group_leader_with_child() -> asyncio.subprocess.Process:
    # The shell waits on a child, so the child only dies if the whole group is signalled.
    return await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        "sleep 600 & wait",
        start_new_session=True,
    )


@pytest.mark.posix_only("POSIX process groups and signals")
@pytest.mark.parametrize(
    # Names, not values: Windows has no SIGKILL, and collection must not fail there.
    ("method", "signal_name"),
    [("terminate", "SIGTERM"), ("kill", "SIGKILL")],
)
async def test_posix_signals_the_whole_process_group(method: str, signal_name: str) -> None:
    signum = getattr(signal, signal_name)
    process = await _group_leader_with_child()
    terminator = PosixProcessGroupTerminator()
    assert getattr(terminator, method)(process.pid)
    assert await process.wait() == -signum
    # The group is empty now: nothing is left to signal.
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)


@pytest.mark.posix_only("POSIX process groups and signals")
async def test_a_process_that_is_already_gone_reports_false() -> None:
    process = await _group_leader_with_child()
    os.killpg(process.pid, signal.SIGKILL)
    await process.wait()
    assert not PosixProcessGroupTerminator().kill(process.pid)


def test_the_registry_answers_by_platform_family() -> None:
    assert isinstance(default_terminators.create("posix"), PosixProcessGroupTerminator)
    assert isinstance(default_terminators.create("nt"), WindowsTaskkillTerminator)
    with pytest.raises(UnsupportedPlatformError, match="'java'"):
        default_terminators.create("java")


def test_each_terminator_names_how_to_start_a_stoppable_tree() -> None:
    assert PosixProcessGroupTerminator().popen_options() == {"start_new_session": True}
    assert WindowsTaskkillTerminator().popen_options() == {
        "creationflags": CREATE_NEW_PROCESS_GROUP
    }


class FakeTaskkill:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


def windows(taskkill: FakeTaskkill, *alive: bool) -> WindowsTaskkillTerminator:
    """A terminator whose process table answers `alive` in turn."""
    answers = iter(alive)
    return WindowsTaskkillTerminator(taskkill, lambda pid: next(answers))


@pytest.mark.parametrize(("method", "flags"), [("terminate", ["/T"]), ("kill", ["/T", "/F"])])
def test_windows_stops_the_tree_with_taskkill(method: str, flags: list[str]) -> None:
    taskkill = FakeTaskkill(0)
    assert getattr(windows(taskkill, True), method)(4242)
    assert taskkill.calls == [["taskkill", "/PID", "4242", *flags]]


@pytest.mark.parametrize("method", ["terminate", "kill"])
def test_windows_reports_a_missing_process_as_false_without_taskkill(method: str) -> None:
    taskkill = FakeTaskkill(0)
    assert not getattr(windows(taskkill, False), method)(4242)
    assert taskkill.calls == []


def test_a_graceful_request_a_console_process_refuses_still_counts_as_asked() -> None:
    assert windows(FakeTaskkill(128), True).terminate(4242)


def test_a_kill_that_races_the_process_exit_is_not_an_error() -> None:
    assert windows(FakeTaskkill(128), True, False).kill(4242)


def test_a_kill_that_leaves_the_process_is_an_error() -> None:
    taskkill = FakeTaskkill(1, b"ERROR: Access is denied.")
    with pytest.raises(OSError, match="Access is denied"):
        windows(taskkill, True, True).kill(4242)


def test_another_platform_is_one_registration() -> None:
    registry = TerminatorRegistry()
    registry.register("nt", PosixProcessGroupTerminator)
    assert isinstance(registry.create("nt"), PosixProcessGroupTerminator)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("nt", PosixProcessGroupTerminator)
