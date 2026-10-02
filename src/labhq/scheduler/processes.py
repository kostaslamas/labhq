"""Process termination behind a per-platform interface (plan §7 and §9).

POSIX kills the whole process group, so tools a run spawned die with it. Windows joins
later as one registration (`taskkill /T`), with no change to the callers.
"""

import os
import signal
from collections.abc import Callable
from typing import Protocol


class ProcessTerminator(Protocol):
    def terminate(self, pid: int) -> None:
        """Ask the process tree rooted at `pid` to stop."""

    def kill(self, pid: int) -> None:
        """Stop the process tree rooted at `pid` without asking."""


class PosixProcessGroupTerminator:
    """Signals the group `pid` leads; the child must start with `start_new_session=True`."""

    def terminate(self, pid: int) -> None:
        self._signal(pid, signal.SIGTERM)

    def kill(self, pid: int) -> None:
        self._signal(pid, signal.SIGKILL)

    @staticmethod
    def _signal(pid: int, signum: signal.Signals) -> None:
        try:
            os.killpg(os.getpgid(pid), signum)
        except ProcessLookupError:
            # Already gone: the outcome the caller wanted.
            return


class UnsupportedPlatformError(LookupError):
    pass


TerminatorFactory = Callable[[], ProcessTerminator]

_TERMINATORS: dict[str, TerminatorFactory] = {
    "posix": PosixProcessGroupTerminator,
}


def register_terminator(platform: str, factory: TerminatorFactory) -> None:
    if platform in _TERMINATORS:
        raise ValueError(f"a terminator for {platform!r} is already registered")
    _TERMINATORS[platform] = factory


def terminator_for(platform: str = os.name) -> ProcessTerminator:
    """The terminator for an `os.name` value."""
    try:
        factory = _TERMINATORS[platform]
    except KeyError:
        raise UnsupportedPlatformError(f"no process terminator for {platform!r}") from None
    return factory()
