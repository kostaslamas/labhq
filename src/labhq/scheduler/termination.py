"""Process termination behind a per-platform interface (plan §7, §9).

POSIX signals a whole process group, so the tools an agent spawned stop with it. Windows
joins later as one more registration (`taskkill /T`), with no change to the callers.
"""

import os
import signal
import sys
from collections.abc import Callable
from typing import Protocol


class ProcessTerminator(Protocol):
    def terminate(self, pid: int) -> bool:
        """Ask the process tree to stop. False when it is already gone."""
        ...

    def kill(self, pid: int) -> bool:
        """Stop the process tree without asking. False when it is already gone."""
        ...


class PosixProcessGroupTerminator:
    """Signals the process group led by `pid`; the run must start it in a new session."""

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
