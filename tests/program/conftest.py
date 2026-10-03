import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from labhq.clock import FakeClock
from labhq.program import LoopRegistry, Services, Step
from tests.approvals.conftest import isolated_git, remote, repo, sessions, world

__all__ = ["isolated_git", "remote", "repo", "sessions", "world"]


class SteppedClock(FakeClock):
    """A clock whose `sleep` waits until the test advances time past the wake-up instant."""

    def __init__(self) -> None:
        super().__init__(datetime(2026, 10, 2, 9, 0, tzinfo=UTC))
        self._sleepers: list[tuple[datetime, asyncio.Future[None]]] = []

    async def sleep(self, seconds: float) -> None:
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sleepers.append((self.now() + timedelta(seconds=seconds), waiter))
        await waiter

    async def yield_to_loop(self) -> None:
        # FakeClock.sleep yields to the event loop without waiting; the sleep guard bans the
        # direct call, and this is what the tests mean by it.
        await FakeClock.sleep(self, 0)

    async def tick(self, seconds: float) -> None:
        """Move time forward one step and wake every sleeper that is now due."""
        now = self.advance(seconds)
        due = [entry for entry in self._sleepers if entry[0] <= now]
        self._sleepers = [entry for entry in self._sleepers if entry not in due]
        for _, waiter in due:
            if not waiter.done():
                waiter.set_result(None)
        await self.yield_to_loop()


class Passes:
    """Counts finished passes per loop, so a test waits for a pass instead of for time."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._changed = asyncio.Condition()

    def watch(self, name: str, step: Step) -> Step:
        async def observed() -> object:
            try:
                return await step()
            finally:
                async with self._changed:
                    self._counts[name] = self._counts.get(name, 0) + 1
                    self._changed.notify_all()

        return observed

    async def reached(self, name: str, count: int) -> None:
        async with self._changed:
            await self._changed.wait_for(lambda: self._counts.get(name, 0) >= count)


def observed(registry: LoopRegistry[Services], passes: Passes) -> LoopRegistry[Services]:
    """A copy of `registry` whose every step reports to `passes`."""
    copy: LoopRegistry[Services] = LoopRegistry()
    for spec in registry:
        copy.register(
            spec.name,
            spec.interval_setting,
            lambda services, spec=spec: passes.watch(spec.name, spec.build(services)),  # type: ignore[misc]
        )
    return copy


@pytest.fixture
def stepped() -> SteppedClock:
    return SteppedClock()
