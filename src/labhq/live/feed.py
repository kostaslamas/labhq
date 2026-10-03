"""The change feed: one pass reads every topic's watermark and publishes what moved.

It polls the database rather than hooking the ORM because the CLI, hooks and agents write
to SQLite from other processes; a watermark sees their commits as well as ours. The program
loop paces it (`live_interval_seconds`) on the injected clock.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.cli.context import Context
from labhq.live.broker import Broker, Change, default_broker
from labhq.live.registry import Topic, TopicRegistry, default_topics

log = logging.getLogger(__name__)


def render(row: tuple[Any, ...]) -> str:
    return "|".join("" if value is None else str(value) for value in row)


class ChangeFeed:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        broker: Broker,
        topics: TopicRegistry = default_topics,
    ) -> None:
        self._sessions = sessions
        self._broker = broker
        self._topics = topics
        self._seen: dict[str, str] = {}

    async def poll(self) -> int:
        """Publish every topic whose watermark moved since the last pass; return how many."""
        published = 0
        for topic in self._topics:
            try:
                watermark = await self._read(topic)
            except Exception:
                # One broken topic must not starve the others; the next pass retries it.
                log.exception("live topic %s: reading the watermark failed", topic.name)
                continue
            if self._seen.get(topic.name) == watermark:
                continue
            self._seen[topic.name] = watermark
            self._broker.publish(Change(topic.name, watermark))
            published += 1
        return published

    async def _read(self, topic: Topic) -> str:
        # A session per topic, so a failed query cannot leave the next one in a bad transaction.
        async with self._sessions() as db:
            row = (await db.execute(topic.query())).one()
        return render(tuple(row))


class HasContext(Protocol):
    @property
    def context(self) -> Context: ...


def live_feed(services: HasContext) -> Callable[[], Awaitable[int]]:
    """The program loop's step: `labhq.program.services` registers it as `live`."""
    return ChangeFeed(services.context.sessions, default_broker).poll
