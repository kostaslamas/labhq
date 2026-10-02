"""The collector samples the local machine through psutil, stubbed here."""

import psutil
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import HealthSample, Host
from labhq.health.collector import collect_local, read_local_metrics
from tests.health.factories import StubPsutil


async def test_collector_writes_samples_for_the_local_machine(
    session: AsyncSession, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    await collect_local(session, clock, "labhq-box")
    await session.commit()

    host = await session.scalar(select(Host))
    assert host is not None
    assert (host.name, host.is_local) == ("labhq-box", True)
    rows = (await session.scalars(select(HealthSample))).all()
    seen = {(row.metric, row.subject): row.value for row in rows}
    assert seen == {
        ("cpu.percent", None): 12.5,
        ("memory.percent", None): 40.0,
        ("memory.available_bytes", None): float(8 * 1024**3),
        ("load.1m", None): 0.5,
        ("load.5m", None): 0.25,
        ("load.15m", None): 0.125,
        ("disk.percent", "/"): 55.0,
        ("disk.percent", "/data"): 91.0,
        ("temperature.celsius", "coretemp/Package id 0"): 48.0,
    }
    assert {row.host_id for row in rows} == {host.id}
    assert {row.sampled_at for row in rows} == {clock.now()}


async def test_collector_creates_the_local_host_only_once(
    session: AsyncSession, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    await collect_local(session, clock, "labhq-box")
    clock.advance(300)
    await collect_local(session, clock, "labhq-box")

    assert await session.scalar(select(func.count()).select_from(Host)) == 1
    times = await session.scalars(select(HealthSample.sampled_at).distinct())
    assert len(times.all()) == 2


def test_missing_temperature_support_yields_no_temperature(
    monkeypatch: pytest.MonkeyPatch, stub_psutil: StubPsutil
) -> None:
    monkeypatch.delattr(psutil, "sensors_temperatures")
    metrics = {reading.metric for reading in read_local_metrics()}
    assert "temperature.celsius" not in metrics
    assert "cpu.percent" in metrics


def test_an_unreadable_mount_is_skipped(
    monkeypatch: pytest.MonkeyPatch, stub_psutil: StubPsutil
) -> None:
    def disk_usage(mount: str) -> object:
        raise PermissionError(mount)

    monkeypatch.setattr(psutil, "disk_usage", disk_usage)
    assert not [r for r in read_local_metrics() if r.metric == "disk.percent"]


def test_a_failing_probe_does_not_cost_the_others_their_sample(
    monkeypatch: pytest.MonkeyPatch, stub_psutil: StubPsutil
) -> None:
    def getloadavg() -> tuple[float, float, float]:
        raise OSError("no load average here")

    monkeypatch.setattr(psutil, "getloadavg", getloadavg)
    metrics = {reading.metric for reading in read_local_metrics()}
    assert "load.1m" not in metrics
    assert {"cpu.percent", "memory.percent", "disk.percent"} <= metrics
