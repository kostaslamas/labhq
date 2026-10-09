"""Channels: added, tested and removed; every enabled one gets a message; secrets stay out."""

import dataclasses
import stat
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.channels import (
    ChannelConfigError,
    ChannelNotFoundError,
    ChannelRuntime,
    FanOutNotifier,
    add_channel,
    copy,
    list_channels,
    remove_channel,
    set_enabled,
)
from labhq.channels.setup import create_and_test
from labhq.clock import FakeClock
from labhq.db.models import CeoReport
from labhq.notify import Message, NotifyError
from tests.channels.conftest import Outbound

TOKEN = "123456:SECRET-TOKEN-VALUE"
TELEGRAM = {"chat_id": "42", "token": TOKEN}
NTFY = {"topic": "labhq-test"}


async def make(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    kind: str,
    name: str,
    values: dict[str, str],
) -> tuple[int, str | None]:
    row, error = await create_and_test(
        sessions, runtime, runtime.data_dir, clock, kind=kind, name=name, values=values
    )
    return row.id, error


async def test_a_channel_is_added_tested_and_the_result_is_stored(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    outbound: Outbound,
) -> None:
    channel_id, error = await make(sessions, runtime, clock, "telegram", "phone", TELEGRAM)

    assert error is None
    assert outbound.hosts() == ["api.telegram.org"]
    async with sessions() as db:
        [row] = await list_channels(db)
        reports = list(await db.scalars(select(CeoReport)))
    assert (row.id, row.last_test_ok, row.last_test_error) == (channel_id, True, None)
    assert row.config == {"chat_id": "42"}
    assert [r.refs for r in reports] == [["channel:phone"]]


async def test_a_failed_test_is_shown_and_the_ceo_is_not_told_it_is_live(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    outbound: Outbound,
) -> None:
    outbound.statuses = [500]

    _, error = await make(sessions, runtime, clock, "ntfy", "topic", NTFY)

    assert error is not None
    async with sessions() as db:
        [row] = await list_channels(db)
        assert list(await db.scalars(select(CeoReport))) == []
    assert row.last_test_ok is False and row.last_test_error == error


async def test_the_token_is_kept_owner_only_outside_the_database_and_never_returned(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    database_url: str,
) -> None:
    channel_id, _ = await make(sessions, runtime, clock, "telegram", "phone", TELEGRAM)

    secret = runtime.data_dir / "channels" / f"{channel_id}.json"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    async with sessions() as db:
        [row] = await list_channels(db)
    assert TOKEN not in repr(row.config) and "token" not in row.config
    database = Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    assert TOKEN.encode() not in database.read_bytes()


async def test_removing_a_channel_removes_its_secret(
    sessions: async_sessionmaker[AsyncSession], runtime: ChannelRuntime, clock: FakeClock
) -> None:
    channel_id, _ = await make(sessions, runtime, clock, "telegram", "phone", TELEGRAM)

    async with sessions() as db:
        await remove_channel(db, runtime.data_dir, channel_id)
        await db.commit()
        assert await list_channels(db) == []
        with pytest.raises(ChannelNotFoundError):
            await remove_channel(db, runtime.data_dir, channel_id)
    assert not (runtime.data_dir / "channels" / f"{channel_id}.json").exists()


@pytest.mark.parametrize(
    ("kind", "name", "values"),
    [
        ("pigeon", "x", {}),
        ("telegram", "x", {"chat_id": "42"}),
        ("telegram", "x", {"chat_id": "not a chat", "token": "t"}),
        ("ntfy", "x", {"topic": "a b"}),
        ("ntfy", "x", {"topic": "ok", "surprise": "1"}),
        ("ntfy", "  ", {"topic": "ok"}),
    ],
)
async def test_bad_input_is_refused(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    kind: str,
    name: str,
    values: dict[str, str],
) -> None:
    async with sessions() as db:
        with pytest.raises(ChannelConfigError) as refused:
            await add_channel(
                db, runtime.data_dir, kind=kind, name=name, values=values, now=clock.now()
            )
    assert TOKEN not in str(refused.value)


async def test_a_name_is_used_once(
    sessions: async_sessionmaker[AsyncSession], runtime: ChannelRuntime, clock: FakeClock
) -> None:
    await make(sessions, runtime, clock, "ntfy", "same", NTFY)

    async with sessions() as db:
        with pytest.raises(ChannelConfigError, match="already exists"):
            await add_channel(
                db, runtime.data_dir, kind="ntfy", name="same", values=NTFY, now=clock.now()
            )


class Recorder:
    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)


async def test_a_message_reaches_every_enabled_channel_and_no_disabled_one(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    outbound: Outbound,
) -> None:
    await make(sessions, runtime, clock, "ntfy", "a", {"topic": "aaa"})
    off, _ = await make(sessions, runtime, clock, "ntfy", "b", {"topic": "bbb"})
    await make(sessions, runtime, clock, "telegram", "c", TELEGRAM)
    async with sessions() as db:
        await set_enabled(db, off, False)
        await db.commit()
    outbound.requests.clear()
    fallback = Recorder()

    await FanOutNotifier(runtime, fallback).send(Message("t", "b", "https://x.example/y"))

    assert sorted(request.url.host or "" for request in outbound.requests) == [
        "api.telegram.org",
        "ntfy.sh",
    ]
    assert fallback.sent == []


async def test_with_no_channel_the_configured_notifier_still_notifies(
    runtime: ChannelRuntime,
) -> None:
    fallback = Recorder()

    await FanOutNotifier(runtime, fallback).send(Message("t", "b"))

    assert len(fallback.sent) == 1


async def test_one_failing_channel_does_not_stop_the_others_and_is_named(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
    outbound: Outbound,
) -> None:
    await make(sessions, runtime, clock, "ntfy", "first", {"topic": "aaa"})
    await make(sessions, runtime, clock, "ntfy", "second", {"topic": "bbb"})
    outbound.requests.clear()
    outbound.statuses = [500]

    with pytest.raises(NotifyError) as failure:
        await FanOutNotifier(runtime, Recorder()).send(Message("t", "b"))

    assert len(outbound.requests) == 2 and "first" in str(failure.value)
    assert "second" not in str(failure.value)


async def test_a_chat_service_is_a_channel_one_thread_per_message(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    clock: FakeClock,
) -> None:
    from labhq.approvals.registry import Registry
    from labhq.chat.bindings import BindingStore
    from labhq.chat.fake import FakeChatAdapter, FakeChatService
    from labhq.chat.registry import ChatAdapterFactory

    service = FakeChatService()
    chat: Registry[ChatAdapterFactory] = Registry("chat adapter")
    chat.register(
        "discord",
        lambda context: FakeChatAdapter(
            service, BindingStore(context.sessions, "fake", clock=context.clock)
        ),
    )
    chat_runtime = dataclasses.replace(runtime, chat=chat)

    channel_id, error = await make(sessions, chat_runtime, clock, "discord", "server", {})
    await FanOutNotifier(chat_runtime, Recorder()).send(
        Message("login needed", "body", "https://auth.openai.com/x")
    )

    assert error is None and channel_id > 0
    posts = [post.text for thread in service.posts.values() for post in thread]
    assert len(posts) == 2 and "https://auth.openai.com/x" in posts[1]
    assert sorted(service.threads.values()) == sorted(["login needed", copy.TEST_TITLE])


async def test_a_chat_service_that_is_not_set_up_fails_the_test_with_a_plain_reason(
    sessions: async_sessionmaker[AsyncSession], runtime: ChannelRuntime, clock: FakeClock
) -> None:
    from labhq.approvals.registry import Registry

    empty = dataclasses.replace(runtime, chat=Registry("chat adapter"))

    _, error = await make(sessions, empty, clock, "slack", "team", {})

    assert error == "slack is not set up on this machine"
