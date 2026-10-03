"""Process termination behind a per-platform interface (plan §7, §9).

POSIX signals a whole process group, so the tools an agent spawned stop with it. Windows
has neither signals nor process groups in that sense; `taskkill /T` walks the tree instead.
"""

import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import psutil

# subprocess.CREATE_NEW_PROCESS_GROUP exists only in the Windows stdlib.
CREATE_NEW_PROCESS_GROUP = 0x00000200


class ProcessTerminator(Protocol):
    def popen_options(self) -> Mapping[str, Any]:
        """Keyword arguments that start a process so its tree can be stopped later."""
        ...

    def terminate(self, pid: int) -> bool:
        """Ask the process tree to stop. False when it is already gone."""
        ...

    def kill(self, pid: int) -> bool:
        """Stop the process tree without asking. False when it is already gone."""
        ...


class PosixProcessGroupTerminator:
    """Signals the process group led by `pid`; the run must start it in a new session."""

    def popen_options(self) -> Mapping[str, Any]:
        return {"start_new_session": True}

    def terminate(self, pid: int) -> bool:
        return _signal_group(pid, signal.SIGTERM)

    def kill(self, pid: int) -> bool:
        return _signal_group(pid, signal.SIGKILL)


def _signal_group(pid: int, signum: signal.Signals) -> bool:
    try:
        os.killpg(os.getpgid(pid), signum)
    except ProcessLookupError:
        return False
    return True


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[bytes]"]


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(argv, capture_output=True, check=False)


class WindowsTaskkillTerminator:
    """Stops the tree rooted at `pid` with `taskkill /T`; the run starts it in a new group.

    taskkill exits 128 both for a missing PID and for a process that refuses to close, so
    whether a process is there is asked of the process table, not of the exit status.
    """

    def __init__(
        self, run: Runner = _run, exists: Callable[[int], bool] = psutil.pid_exists
    ) -> None:
        self._run = run
        self._exists = exists

    def popen_options(self) -> Mapping[str, Any]:
        # A new group keeps a console Ctrl+C aimed at labhq away from the run's tree.
        return {"creationflags": CREATE_NEW_PROCESS_GROUP}

    def terminate(self, pid: int) -> bool:
        if not self._exists(pid):
            return False
        # Without /F, taskkill asks windows to close, and a console process without one
        # refuses: that is an answer, not an error, and the caller escalates to kill.
        self._taskkill(pid)
        return True

    def kill(self, pid: int) -> bool:
        if not self._exists(pid):
            return False
        result = self._taskkill(pid, "/F")
        if result.returncode != 0 and self._exists(pid):
            message = result.stderr.decode(errors="replace").strip()
            raise OSError(f"taskkill could not stop process tree {pid}: {message}")
        return True

    def _taskkill(self, pid: int, *flags: str) -> "subprocess.CompletedProcess[bytes]":
        return self._run(["taskkill", "/PID", str(pid), "/T", *flags])


TerminatorFactory = Callable[[], ProcessTerminator]


class UnsupportedPlatformError(LookupError):
    pass


class TerminatorRegistry:
    """`platform family -> factory`, keyed like `os.name` ("posix", "nt")."""

    def __init__(self) -> None:
        self._factories: dict[str, TerminatorFactory] = {}

    def register(self, family: str, factory: TerminatorFactory) -> None:
        if family in self._factories:
            raise ValueError(f"platform {family!r} is already registered")
        self._factories[family] = factory

    def create(self, family: str | None = None) -> ProcessTerminator:
        key = family or os.name
        try:
            return self._factories[key]()
        except KeyError:
            raise UnsupportedPlatformError(
                f"no process terminator for {key!r} ({sys.platform})"
            ) from None


default_terminators = TerminatorRegistry()
default_terminators.register("posix", PosixProcessGroupTerminator)
default_terminators.register("nt", WindowsTaskkillTerminator)
