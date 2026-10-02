"""What the scheduler hands to a run, and how a dispatched run is started.

The preparer turns a wakeup into a prompt, a working directory and hooks; the CLI wires
worktrees and the push guard in through it. The launcher starts the run. Both are
injected, so the scheduler knows neither worktrees nor adapters.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from labhq.db.models import WakeupRequest
from labhq.runs import ActiveRun, RunService


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    prompt: str
    cwd: Path | None = None
    hooks: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    agent_id: int
    task_id: int | None
    # The queued run that already holds the task's checkout.
    run_id: int
    spec: LaunchSpec


class LaunchedRun(Protocol):
    @property
    def pid(self) -> int | None:
        """The root of the run's process tree, when the launcher knows it."""

    async def wait(self) -> object:
        """Drive the run to its terminal status."""

    async def interrupt(self) -> None: ...


Preparer = Callable[[WakeupRequest], Awaitable[LaunchSpec]]
Launcher = Callable[[LaunchRequest], Awaitable[LaunchedRun]]


async def default_preparer(request: WakeupRequest) -> LaunchSpec:
    merged = f" ({request.coalesced_count} more wakeups merged)" if request.coalesced_count else ""
    return LaunchSpec(prompt=f"Woken by {request.source}: {request.reason}{merged}")


class _ServiceRun:
    # The SDK owns the Claude Code process and does not expose it; closing the adapter
    # stops it instead.
    pid: int | None = None

    def __init__(self, active: ActiveRun) -> None:
        self._active = active

    async def wait(self) -> object:
        return await self._active.wait()

    async def interrupt(self) -> None:
        await self._active.interrupt()


def run_service_launcher(service: RunService) -> Launcher:
    async def launch(request: LaunchRequest) -> LaunchedRun:
        active = await service.start(
            agent_id=request.agent_id,
            task_id=request.task_id,
            prompt=request.spec.prompt,
            cwd=request.spec.cwd,
            hooks=request.spec.hooks,
            run_id=request.run_id,
        )
        return _ServiceRun(active)

    return launch
