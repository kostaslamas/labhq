import logging
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval
from labhq.live.broker import Broker, Change, Subscription
from labhq.live.feed import ChangeFeed, live_feed
from labhq.live.registry import TopicRegistry, aggregates, default_topics
from labhq.program import ProgramSettings, default_loops
from labhq.program.loops import run_loop

INTERVAL = ProgramSettings().live_interval_seconds


class StopLoop(BaseException):
    """Ends `run_loop` the way cancellation does: it is not an `Exception`."""


@pytest.fixture
async def writer(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Another process's connection: its own engine, nothing shared with the feed."""
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


async def insert_approval(writer: async_sessionmaker[AsyncSession], clock: FakeClock) -> int:
    async with writer() as db:
        approval = Approval(type="push", risk_class=RiskClass.LIGHT, created_at=clock.now())
        db.add(approval)
        await db.commit()
        return approval.id


def pending(subscription: Subscription) -> dict[str, str]:
    return dict(subscription._pending)


async def test_the_live_loop_polls_every_second_by_default() -> None:
    spec = next(spec for spec in default_loops if spec.name == "live")
    assert spec.interval(ProgramSettings()) == 1.0
    assert spec.build is live_feed


async def test_phase_4_registers_its_six_topics() -> None:
    assert set(default_topics.names()) >= {
        "approvals",
        "tasks",
        "runs",
        "costs",
        "questions",
        "incidents",
    }


async def test_an_approval_from_another_session_is_published_within_one_interval(
    sessions: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    broker: Broker,
    clock: FakeClock,
) -> None:
    feed = ChangeFeed(sessions, broker)
    await feed.poll()  # The baseline: every topic once.
    with broker.subscribe() as subscription:
        await insert_approval(writer, clock)
        inserted_at = clock.now()
        await clock.sleep(INTERVAL)
        assert await feed.poll() == 1
        assert (clock.now() - inserted_at).total_seconds() <= INTERVAL
        changes = await subscription.get()
    assert changes is not None
    assert [change.topic for change in changes] == ["approvals"]


async def test_a_decision_moves_the_watermark_without_a_new_row(
    sessions: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    broker: Broker,
    clock: FakeClock,
) -> None:
    approval_id = await insert_approval(writer, clock)
    feed = ChangeFeed(sessions, broker)
    await feed.poll()
    with broker.subscribe() as subscription:
        async with writer() as db:
            await db.execute(
                update(Approval)
                .where(Approval.id == approval_id)
                .values(status=ApprovalStatus.CANCELLED)
            )
            await db.commit()
        await feed.poll()
        assert list(pending(subscription)) == ["approvals"]


async def test_an_unchanged_watermark_publishes_nothing(
    sessions: async_sessionmaker[AsyncSession], broker: Broker
) -> None:
    feed = ChangeFeed(sessions, broker)
    assert await feed.poll() == len(default_topics)
    with broker.subscribe() as subscription:
        assert await feed.poll() == 0
        assert pending(subscription) == {}


async def test_a_failing_watermark_is_logged_and_retried_while_other_topics_run(
    sessions: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    broker: Broker,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    failures = [RuntimeError("database is locked")]

    def flaky() -> Select[tuple[int]]:
        if failures:
            raise failures.pop()
        return select(1)

    topics = TopicRegistry()
    topics.register("flaky", flaky)
    topics.register("approvals", aggregates(func.max(Approval.id), func.count(Approval.id)))
    feed = ChangeFeed(sessions, broker, topics)
    passes = 0

    async def step() -> int:
        nonlocal passes
        passes += 1
        if passes == 1:
            await insert_approval(writer, clock)
        published = await feed.poll()
        if passes == 2:
            raise StopLoop
        return published

    with broker.subscribe() as subscription, caplog.at_level(logging.ERROR):
        with pytest.raises(StopLoop):
            await run_loop("live", INTERVAL, step, clock)
        seen = pending(subscription)
    assert "live topic flaky: reading the watermark failed" in caplog.text
    assert "approvals" in seen, "the other topic kept publishing"
    assert seen["flaky"] == "1", "the failed topic was read again on the next tick"


async def test_a_published_change_reaches_every_subscriber_coalesced() -> None:
    broker = Broker()
    with broker.subscribe() as first, broker.subscribe() as second:
        broker.publish(Change("tasks", "1"))
        broker.publish(Change("tasks", "2"))
        assert await first.get() == [Change("tasks", "2")]
        assert await second.get() == [Change("tasks", "2")]
    assert len(broker) == 0
