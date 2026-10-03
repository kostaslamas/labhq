"""Process termination: a per-platform registry, POSIX signalling the whole group."""

import asyncio
import os
import signal
import sys

import pytest

from labhq.scheduler import (
    PosixProcessGroupTerminator,
    TerminatorRegistry,
    UnsupportedPlatformError,
    default_terminators,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")


async def _group_leader_with_child() -> asyncio.subprocess.Process:
    # The shell waits on a child, so the child only dies if the whole group is signalled.
    return await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        "sleep 600 & wait",
        start_new_session=True,
    )


@posix_only
@pytest.mark.parametrize(
    ("method", "signum"), [("terminate", signal.SIGTERM), ("kill", signal.SIGKILL)]
)
async def test_posix_signals_the_whole_process_group(method: str, signum: int) -> None:
    process = await _group_leader_with_child()
    terminator = PosixProcessGroupTerminator()
    assert getattr(terminator, method)(process.pid)
    assert await process.wait() == -signum
    # The group is empty now: nothing is left to signal.
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)


@posix_only
async def test_a_process_that_is_already_gone_reports_false() -> None:
    process = await _group_leader_with_child()
    os.killpg(process.pid, signal.SIGKILL)
    await process.wait()
    assert not PosixProcessGroupTerminator().kill(process.pid)


def test_the_registry_answers_by_platform_family() -> None:
    assert isinstance(default_terminators.create("posix"), PosixProcessGroupTerminator)
    with pytest.raises(UnsupportedPlatformError, match=sys.platform):
        default_terminators.create("nt")


def test_another_platform_is_one_registration() -> None:
    registry = TerminatorRegistry()
    registry.register("nt", PosixProcessGroupTerminator)
    assert isinstance(registry.create("nt"), PosixProcessGroupTerminator)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("nt", PosixProcessGroupTerminator)
