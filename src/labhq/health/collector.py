"""Samples the local machine with psutil and stores the readings as `health_samples`."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import HostStatus
from labhq.db.models import HealthSample, Host

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    metric: str
    value: float
    # A mount point or a sensor when the metric has several; None otherwise.
    subject: str | None = None


Probe = Callable[[], list[Reading]]


def _cpu() -> list[Reading]:
    # Non-blocking: the percentage since the previous call. The first call of a process
    # reports 0.0, which the next interval corrects.
    return [Reading("cpu.percent", float(psutil.cpu_percent(interval=None)))]


def _memory() -> list[Reading]:
    memory = psutil.virtual_memory()
    return [
        Reading("memory.percent", float(memory.percent)),
        Reading("memory.available_bytes", float(memory.available)),
    ]


def _load() -> list[Reading]:
    one, five, fifteen = psutil.getloadavg()
    return [
        Reading("load.1m", float(one)),
        Reading("load.5m", float(five)),
        Reading("load.15m", float(fifteen)),
    ]


def _disks() -> list[Reading]:
    readings = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:
            # Unready media and mounts we may not stat are not a reason to lose the sample.
            logger.debug("skipping unreadable mount %s", partition.mountpoint)
            continue
        readings.append(Reading("disk.percent", float(usage.percent), partition.mountpoint))
    return readings


def _temperatures() -> list[Reading]:
    # psutil reports temperatures only on some platforms; elsewhere the function is absent.
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is None:
        return []
    readings = []
    for chip, entries in sensors().items():
        for index, entry in enumerate(entries):
            label = entry.label or str(index)
            readings.append(Reading("temperature.celsius", float(entry.current), f"{chip}/{label}"))
    return readings


# A new metric family is a new probe here, not an edit to `read_local_metrics`.
PROBES: tuple[Probe, ...] = (_cpu, _memory, _load, _disks, _temperatures)


def read_local_metrics(probes: tuple[Probe, ...] = PROBES) -> list[Reading]:
    readings: list[Reading] = []
    for probe in probes:
        try:
            readings.extend(probe())
        except (OSError, NotImplementedError, AttributeError):
            # One failing probe must not cost the other metrics their sample.
            logger.warning("health probe %s failed", probe.__name__, exc_info=True)
    return readings


async def local_host(session: AsyncSession, clock: Clock, name: str) -> Host:
    """Return the local `hosts` row, creating it on first run."""
    host = await session.scalar(select(Host).where(Host.is_local.is_(True)))
    if host is not None:
        return host
    now = clock.now()
    host = Host(name=name, is_local=True, status=HostStatus.UP, created_at=now, updated_at=now)
    session.add(host)
    await session.flush()
    return host


async def collect_local(
    session: AsyncSession,
    clock: Clock,
    host_name: str,
    probes: tuple[Probe, ...] = PROBES,
) -> list[HealthSample]:
    """Sample the local machine once. The caller owns the transaction."""
    host = await local_host(session, clock, host_name)
    sampled_at = clock.now()
    samples = [
        HealthSample(
            host_id=host.id,
            metric=reading.metric,
            subject=reading.subject,
            value=reading.value,
            sampled_at=sampled_at,
        )
        for reading in read_local_metrics(probes)
    ]
    session.add_all(samples)
    await session.flush()
    return samples
