"""Socket Mode: only the owner's replies in labhq threads come back, across reconnects."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import ChatError
from labhq.chat.contract import Speaker
from labhq.chat.slack import SlackAdapter
from tests.chat.fake_discord import SteppedClock
from tests.chat.fake_slack import OWNER_ID, SOCKET_URL, SlackHarness


@pytest.fixture
async def slack(
    sessions: async_sessionmaker[AsyncSession], stepped_clock: SteppedClock
) -> AsyncIterator[SlackHarness]:
    harness = SlackHarness(sessions, stepped_clock)
    async with harness.client:
        yield harness


async def _listening(harness: SlackHarness) -> tuple[SlackAdapter, str, str]:
    adapter = harness.adapter()
    channel = await adapter.ensure_channel("demo", "Demo")
    thread = await adapter.open_thread(channel, "Standup")
    return adapter, channel.id, thread.id


async def test_only_the_owners_reply_in_a_labhq_thread_is_yielded(slack: SlackHarness) -> None:
    adapter, channel_id, thread_id = await _listening(slack)
    replies = adapter.replies()
    for speaker in (Speaker.BOT, Speaker.WEBHOOK, Speaker.OTHER_USER):
        slack.socket.deliver(speaker, thread_id, f"from {speaker}")
    slack.socket.deliver(Speaker.OWNER, channel_id, "outside any thread")
    slack.socket.deliver(Speaker.OWNER, f"{channel_id}:1727869999.000001", "not a labhq thread")
    slack.socket.deliver(Speaker.OWNER, f"C0700000999:{thread_id.split(':')[1]}", "other channel")
    slack.socket.deliver(Speaker.OWNER, thread_id, "edited", subtype="message_changed")
    slack.socket.deliver(Speaker.OWNER, thread_id, "ship it")

    reply = await anext(replies)

    assert (reply.text, reply.author, reply.thread.id) == ("ship it", OWNER_ID, thread_id)
    assert reply.ref.startswith("1727861000.")
    await adapter.close()
    assert [late async for late in replies] == []


async def test_the_adapters_own_posts_are_never_echoed(slack: SlackHarness) -> None:
    adapter, _, thread_id = await _listening(slack)
    # Our persona posts come back as bot_message events of our own bot; even one that
    # claimed the owner's user id must be dropped.
    slack.socket.deliver(Speaker.WEBHOOK, thread_id, "echo", user=OWNER_ID)
    slack.socket.deliver(Speaker.OWNER, thread_id, "real")
    assert (await anext(adapter.replies())).text == "real"
    await adapter.close()


async def test_a_reply_also_sent_to_the_channel_still_counts(slack: SlackHarness) -> None:
    adapter, _, thread_id = await _listening(slack)
    slack.socket.deliver(Speaker.OWNER, thread_id, "agreed", subtype="thread_broadcast")
    assert (await anext(adapter.replies())).text == "agreed"
    await adapter.close()


async def test_every_envelope_is_acknowledged_and_a_redelivery_is_yielded_once(
    slack: SlackHarness,
) -> None:
    adapter, _, thread_id = await _listening(slack)
    replies = adapter.replies()
    first = slack.socket.deliver(Speaker.OWNER, thread_id, "once")
    slack.socket.envelopes.put_nowait({**first, "envelope_id": "retry", "retry_attempt": 1})
    slack.socket.deliver(Speaker.OWNER, thread_id, "twice")

    assert [(await anext(replies)).text, (await anext(replies)).text] == ["once", "twice"]
    (connection,) = slack.socket.connections
    assert connection.url == SOCKET_URL
    acked = [payload["envelope_id"] for payload in connection.sent]
    assert acked == [first["envelope_id"], "retry", "envelope-101"]
    await adapter.close()


async def test_a_disconnect_reconnects_after_the_delay_on_the_clock(
    slack: SlackHarness, stepped_clock: SteppedClock
) -> None:
    adapter, _, thread_id = await _listening(slack)
    pending = asyncio.ensure_future(anext(adapter.replies()))
    slack.socket.envelopes.put_nowait({"type": "disconnect", "reason": "refresh_requested"})

    await stepped_clock.sleeping(1)
    assert stepped_clock.sleeps == [5.0]
    stepped_clock.step()
    slack.socket.deliver(Speaker.OWNER, thread_id, "back")

    assert (await pending).text == "back"
    assert len(slack.socket.connections) == 2
    assert len(slack.api.calls("apps.connections.open")) == 2
    await adapter.close()


async def test_a_disabled_link_stops_with_an_error(slack: SlackHarness) -> None:
    adapter, _, _ = await _listening(slack)
    slack.socket.envelopes.put_nowait({"type": "disconnect", "reason": "link_disabled"})
    with pytest.raises(ChatError, match="disabled socket mode"):
        await anext(adapter.replies())
    assert len(slack.socket.connections) == 1
