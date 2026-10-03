"""In-process fan-out of invalidations from the change feed to every open socket.

A subscriber keeps only the newest watermark per topic. Invalidations are idempotent (the
client refetches whatever is current), so a slow socket coalesces instead of queueing, and
memory per subscriber is bounded by the number of topics.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class Change:
    """`topic` changed; `watermark` is opaque and only ever compared for equality."""

    topic: str
    watermark: str


class Subscription:
    def __init__(self) -> None:
        self._pending: dict[str, str] = {}
        self._ready = asyncio.Event()
        self._closed = False

    def offer(self, change: Change) -> None:
        self._pending[change.topic] = change.watermark
        self._ready.set()

    def close(self) -> None:
        self._closed = True
        self._ready.set()

    async def get(self) -> list[Change] | None:
        """Wait for changes and take them all; `None` once the broker closed this subscription."""
        await self._ready.wait()
        if self._closed:
            return None
        self._ready.clear()
        changes = [Change(topic, watermark) for topic, watermark in self._pending.items()]
        self._pending.clear()
        return changes


class Broker:
    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    def publish(self, change: Change) -> None:
        for subscription in self._subscriptions:
            subscription.offer(change)

    @contextmanager
    def subscribe(self) -> Iterator[Subscription]:
        subscription = Subscription()
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def close_all(self) -> None:
        """End every open subscription, so sockets close and the server can stop."""
        for subscription in self._subscriptions:
            subscription.close()

    def __len__(self) -> int:
        return len(self._subscriptions)


# `labhq serve` runs the program loops and the API in one event loop; both use this broker.
default_broker = Broker()
