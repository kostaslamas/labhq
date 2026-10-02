from datetime import UTC, datetime, timedelta, timezone

import pytest

from labhq.clock import FakeClock, SystemClock, ensure_utc


def test_fake_clock_stands_still_until_advanced(clock: FakeClock) -> None:
    start = clock.now()
    assert clock.now() == start
    assert clock.advance(timedelta(minutes=5)) == start + timedelta(minutes=5)
    assert clock.advance(30) == start + timedelta(minutes=5, seconds=30)


async def test_fake_clock_sleep_advances_time_without_waiting(clock: FakeClock) -> None:
    start = clock.now()
    await clock.sleep(3600)
    assert clock.now() - start == timedelta(hours=1)


def test_fake_clock_never_moves_backwards(clock: FakeClock) -> None:
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_fake_clock_instants_are_aware_utc(clock: FakeClock) -> None:
    athens = timezone(timedelta(hours=3))
    clock.set(datetime(2026, 10, 2, 12, 0, tzinfo=athens))
    assert clock.now() == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_fake_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_ensure_utc_rejects_naive_and_converts_offsets() -> None:
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))  # noqa: DTZ001
    plus_two = datetime(2026, 1, 1, 2, 0, tzinfo=timezone(timedelta(hours=2)))
    assert ensure_utc(plus_two) == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
