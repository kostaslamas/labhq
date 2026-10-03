"""The collector's loop: sample every host, evaluate the rules, commit, wait an interval.

Hosts are read in one transaction, collected with no transaction open (an SSH host may take
seconds), and their samples written with the rule evaluation in a second one.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import HostStatus
from labhq.db.models import HealthSample, Host
from labhq.health import collectors
from labhq.health.collector import Reading, local_host
from labhq.health.collectors import (
    CollectionSettings,
    CollectorRegistry,
    HostTarget,
    ProbeContext,
)
from labhq.health.incidents import IncidentChange, evaluate_rules
from labhq.health.rules import RuleRegistry, registry
from labhq.health.settings import HealthSettings
from labhq.health.ssh import HostKeyNotTrustedError, SshError
from labhq.notify.outbox import enqueue

logger = logging.getLogger(__name__)

# What makes one host's collection fail. Anything else is a defect and surfaces.
HOST_FAILURES: tuple[type[Exception], ...] = (SshError, OSError, ValueError, TimeoutError)


@dataclass(frozen=True)
class HostCollection:
    target: HostTarget
    readings: list[Reading]
    error: Exception | None = None


async def collect_host(
    target: HostTarget, context: ProbeContext, kinds: CollectorRegistry
) -> HostCollection:
    """One host, through the collector of its kind; a host that fails is reported, not raised."""
    try:
        readings = await kinds.get(target.kind).read(target, context)
    except HOST_FAILURES as error:
        logger.error("health collection from %s failed: %s", target.name, error)
        return HostCollection(target, [], error)
    return HostCollection(target, readings)


async def _report_untrusted_key(
    db: AsyncSession, collection: HostCollection, now: datetime
) -> None:
    # A changed key is never accepted here; the owner re-adds the host after checking it.
    target = collection.target
    await enqueue(
        db,
        kind="host_key_rejected",
        subject=f"host:{target.id}",
        title=f"Host key of {target.name} not trusted",
        body=f"Collection from {target.name} stopped: {collection.error}",
        idempotency_key=f"host-key:{target.id}:{now:%Y-%m-%d}",
        now=now,
    )


async def record_collection(db: AsyncSession, collection: HostCollection, now: datetime) -> None:
    host = await db.get_one(Host, collection.target.id)
    host.status = HostStatus.DOWN if collection.error is not None else HostStatus.UP
    host.updated_at = now
    db.add_all(
        HealthSample(
            host_id=host.id,
            metric=reading.metric,
            subject=reading.subject,
            value=reading.value,
            sampled_at=now,
        )
        for reading in collection.readings
    )
    if isinstance(collection.error, HostKeyNotTrustedError):
        await _report_untrusted_key(db, collection, now)
    await db.flush()


@dataclass
class HealthMonitor:
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    settings: HealthSettings
    rules: RuleRegistry = registry
    kinds: CollectorRegistry = field(default_factory=lambda: collectors.default_collectors)
    collection: CollectionSettings = field(default_factory=CollectionSettings)

    async def _targets(self, now: datetime) -> list[tuple[HostTarget, ProbeContext]]:
        fallback = now - timedelta(seconds=self.settings.sample_interval_seconds)
        latest = select(HealthSample.host_id, func.max(HealthSample.sampled_at)).group_by(
            HealthSample.host_id
        )
        async with self.sessions() as db, db.begin():
            await local_host(db, self.clock, self.settings.local_host_name)
            hosts = (await db.scalars(select(Host).order_by(Host.id))).all()
            previous = {host_id: at for host_id, at in await db.execute(latest)}
        return [
            (
                HostTarget.of(host),
                ProbeContext(
                    now=now,
                    since=previous.get(host.id, fallback),
                    certificates=self.collection.certificates_for(host.name),
                ),
            )
            for host in hosts
        ]

    async def tick(self) -> list[IncidentChange]:
        now = self.clock.now()
        targets = await self._targets(now)
        collections = await asyncio.gather(
            *(collect_host(target, context, self.kinds) for target, context in targets)
        )
        async with self.sessions() as db, db.begin():
            for collection in collections:
                await record_collection(db, collection, now)
            return await evaluate_rules(db, self.clock, self.rules)

    async def run(self, iterations: int | None = None) -> None:
        """Tick every `sample_interval_seconds`; `iterations` bounds the loop for tests."""
        done = 0
        while iterations is None or done < iterations:
            await self.tick()
            done += 1
            await self.clock.sleep(self.settings.sample_interval_seconds)


class _ProgramContext(Protocol):
    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]: ...

    @property
    def clock(self) -> Clock: ...


class _ProgramServices(Protocol):
    @property
    def context(self) -> _ProgramContext: ...


def health_step(services: _ProgramServices) -> Callable[[], Awaitable[object]]:
    """The always-on program's `health` loop: one tick per pass, paced by the program."""
    context = services.context
    monitor = HealthMonitor(
        context.sessions, context.clock, HealthSettings(), kinds=collectors.default_collectors
    )
    return monitor.tick
