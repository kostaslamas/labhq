"""A database session factory, hosts and collector registries for multi-host health tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db import create_engine, session_factory
from labhq.db.models import Host
from labhq.health.collectors import (
    LOCAL_KIND,
    SSH_KIND,
    Collector,
    CollectorRegistry,
    LocalCollector,
)


@asynccontextmanager
async def open_sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


def kinds(ssh: Collector, local: Collector | None = None) -> CollectorRegistry:
    """The two built-in kinds; the local one reads psutil only, never a real command."""
    registry = CollectorRegistry()
    registry.register(LOCAL_KIND, local or LocalCollector(commands=()))
    registry.register(SSH_KIND, ssh)
    return registry


async def add_remote_host(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    *,
    address: str,
    name: str = "nas",
    ssh_user: str = "labhq-ro",
    intervention_user: str | None = "labhq-fix",
) -> Host:
    now = clock.now()
    host = Host(
        name=name,
        address=address,
        ssh_user=ssh_user,
        intervention_user=intervention_user,
        created_at=now,
        updated_at=now,
    )
    async with sessions() as db, db.begin():
        db.add(host)
    return host
