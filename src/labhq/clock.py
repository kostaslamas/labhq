"""Injectable time source. Every instant in labhq is timezone-aware UTC."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


def ensure_utc(value: datetime) -> datetime:
    """Return `value` in UTC; a naive datetime is a bug, not an implicit local time."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"naive datetime is not allowed: {value!r}")
    return value.astimezone(UTC)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock:
    """A clock that moves only when told to. `sleep` advances time instead of waiting."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = ensure_utc(start) if start else datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta | float) -> datetime:
        step = delta if isinstance(delta, timedelta) else timedelta(seconds=delta)
        if step < timedelta(0):
            raise ValueError("a clock never moves backwards")
        self._now += step
        return self._now

    def set(self, value: datetime) -> None:
        self._now = ensure_utc(value)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        # Yield so other tasks observe the new time, as a real sleep would let them run.
        await asyncio.sleep(0)
