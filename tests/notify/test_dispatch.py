"""Outbox delivery: sent once, retried with backoff, new notifier kinds by registration."""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.clock import FakeClock
from labhq.db.enums import NotificationStatus
from labhq.notify import (
    Dispatcher,
    Message,
    NotifierFactory,
    NotifyError,
    NotifySettings,
    build_notifier,
    enqueue,
    notifiers,
)
from tests.approvals.conftest import World
from tests.notify.conftest import Outbound, all_rows


async def queue(sessions: async_sessionmaker[AsyncSession], clock: FakeClock, key: str) -> None:
    async with sessions() as db:
        await enqueue(
            db,
            kind="test",
            subject=key,
            title="Title",
            body="Body",
            idempotency_key=key,
            click_url="https://example.test/x",
            now=clock.now(),
        )
        await db.commit()


async def test_creating_an_approval_enqueues_one_notification_the_dispatcher_sends(
    world: World, outbound: Outbound, dispatcher_for
) -> None:
    approval = await world.service.request("delete_branch", {"members": ["a"], "lead": "m"})

    rows = await all_rows(world.sessions)
    assert len(rows) == 1
    assert (rows[0].kind, rows[0].subject) == ("approval_requested", f"approval:{approval.id}")
    assert rows[0].idempotency_key == f"approval:{approval.id}"
    assert f"A{approval.id}" in rows[0].body

    dispatcher: Dispatcher = dispatcher_for(outbound, ntfy_topic="t0pic")
    assert await dispatcher.dispatch_pending() == 1

    (request,) = outbound.requests
    assert request.url == "https://ntfy.sh/t0pic"
    assert request.headers["Priority"] == "high"
    assert f"A{approval.id}" in request.content.decode()
    assert (await all_rows(world.sessions))[0].status == NotificationStatus.SENT


async def test_a_failed_send_is_retried_after_backoff_and_a_sent_row_is_never_sent_again(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    outbound: Outbound,
    dispatcher_for,
) -> None:
    await queue(sessions, clock, "k1")
    outbound.statuses = [500, 200]
    dispatcher: Dispatcher = dispatcher_for(outbound, ntfy_topic="t", backoff_base_seconds=30)

    assert await dispatcher.dispatch_pending() == 0
    (row,) = await all_rows(sessions)
    assert (row.status, row.attempts, row.last_error) == (
        NotificationStatus.PENDING,
        1,
        "ntfy answered HTTP 500",
    )

    # Not due yet: nothing is sent before the backoff has passed.
    assert await dispatcher.dispatch_pending() == 0
    assert len(outbound.requests) == 1

    clock.advance(timedelta(seconds=30))
    assert await dispatcher.dispatch_pending() == 1
    (row,) = await all_rows(sessions)
    assert (row.status, row.attempts, row.sent_at) == (NotificationStatus.SENT, 2, clock.now())

    clock.advance(timedelta(days=1))
    assert await dispatcher.dispatch_pending() == 0
    assert len(outbound.requests) == 2


async def test_backoff_doubles_and_a_row_fails_for_good_at_the_attempt_limit(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    outbound: Outbound,
    dispatcher_for,
) -> None:
    await queue(sessions, clock, "k1")
    outbound.statuses = [500, 500, 500]
    dispatcher: Dispatcher = dispatcher_for(
        outbound, ntfy_topic="t", backoff_base_seconds=10, max_attempts=3
    )

    await dispatcher.dispatch_pending()
    clock.advance(10)
    await dispatcher.dispatch_pending()
    (row,) = await all_rows(sessions)
    assert row.next_attempt_at == clock.now() + timedelta(seconds=20)

    clock.advance(20)
    await dispatcher.dispatch_pending()
    (row,) = await all_rows(sessions)
    assert (row.status, row.attempts, row.next_attempt_at) == (NotificationStatus.FAILED, 3, None)

    clock.advance(timedelta(days=1))
    await dispatcher.dispatch_pending()
    assert len(outbound.requests) == 3


async def test_two_dispatchers_send_a_row_once(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    outbound: Outbound,
    dispatcher_for,
) -> None:
    await queue(sessions, clock, "k1")
    first: Dispatcher = dispatcher_for(outbound, ntfy_topic="t")
    second: Dispatcher = dispatcher_for(outbound, ntfy_topic="t")

    # Both read the row as due; only the conditional claim lets one of them send it.
    row_id, attempts = (await all_rows(sessions))[0].id, 0
    assert await first._deliver(row_id, attempts)
    assert not await second._deliver(row_id, attempts)
    assert len(outbound.requests) == 1


async def test_enqueue_returns_the_existing_row_for_a_repeated_key(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await queue(sessions, clock, "same")
    await queue(sessions, clock, "same")
    assert len(await all_rows(sessions)) == 1


async def test_a_new_notifier_kind_is_a_registration_not_a_dispatcher_edit(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path
) -> None:
    delivered: list[Message] = []

    class Dummy:
        async def send(self, message: Message) -> None:
            delivered.append(message)

    registry: Registry[NotifierFactory] = notifiers.copy()
    registry.register("dummy", lambda settings, client, data_dir: Dummy())
    settings = NotifySettings(kind="dummy")
    notifier = build_notifier(settings, httpx.AsyncClient(), tmp_path, registry=registry)
    await queue(sessions, clock, "k1")

    dispatcher = Dispatcher(sessions, notifier, clock=clock, settings=settings)
    assert await dispatcher.dispatch_pending() == 1
    assert [m.title for m in delivered] == ["Title"]


async def test_an_unexpected_notifier_error_is_stored_by_type_only(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    class Boom:
        async def send(self, message: Message) -> None:
            raise RuntimeError("https://host/bot123:SECRET/")

    await queue(sessions, clock, "k1")
    dispatcher = Dispatcher(sessions, Boom(), clock=clock, settings=NotifySettings())
    await dispatcher.dispatch_pending()
    (row,) = await all_rows(sessions)
    assert row.last_error == "RuntimeError"


def test_an_unknown_kind_is_reported_with_its_name(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="carrier-pigeon"):
        build_notifier(NotifySettings(kind="carrier-pigeon"), httpx.AsyncClient(), tmp_path)


def test_notify_error_is_a_runtime_error() -> None:
    assert issubclass(NotifyError, RuntimeError)
