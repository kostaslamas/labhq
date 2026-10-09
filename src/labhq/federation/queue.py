"""Where the `remote` adapter queues its orders: this instance's own database.

A node with an A2A URL is sent the order at once, best effort. A node that is down keeps the
order pending, and the next `federation sync` round sends it, so queueing never fails on the
network.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.models import FederationNode
from labhq.federation.a2a.sync import ClientFactoryFn, sync_once
from labhq.federation.orders import queue_order
from labhq.federation.settings import FederationSettings, get_federation_settings
from labhq.settings import Settings


class DatabaseOrderQueue:
    """An `OrderQueue`. Without sessions it opens the configured database for each order.

    The adapter registry builds adapters without arguments, so the default reads the
    configuration on every call, like the approval executors do.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession] | None = None,
        clock: Clock | None = None,
        *,
        settings: FederationSettings | None = None,
        make_client: ClientFactoryFn | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or SystemClock()
        self._settings = settings
        self._make_client = make_client

    async def queue(self, run_id: int) -> str:
        if self._sessions is not None:
            return await self._queue(self._sessions, run_id)
        engine = create_engine(Settings().resolved_database_url)
        try:
            return await self._queue(session_factory(engine), run_id)
        finally:
            await engine.dispose()

    async def _queue(self, sessions: async_sessionmaker[AsyncSession], run_id: int) -> str:
        async with sessions() as db:
            order = await queue_order(db, self._clock, run_id)
            node = await db.get_one(FederationNode, order.node_id)
            await db.commit()
        queued = f"Order {order.id} queued for node {node.name}."
        if node.a2a_url is None:
            return queued
        settings = self._settings or get_federation_settings()
        result = await sync_once(sessions, self._clock, settings, make_client=self._make_client)
        failure = result.failures.get(node.name)
        if failure is None:
            return f"Order {order.id} sent to node {node.name} over A2A."
        return f"{queued} Not sent yet ({failure}); the next sync retries it."
