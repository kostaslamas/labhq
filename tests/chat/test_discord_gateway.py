"""The gateway client: identify with the right intents, heartbeat, reconnect, give up when fatal."""

import asyncio

import pytest

from labhq.chat import ChatError, Reply
from labhq.chat.contract import Speaker
from labhq.chat.discord import DiscordAdapter
from labhq.chat.discord.gateway import (
    GUILD_MESSAGES,
    GUILDS,
    HEARTBEAT,
    IDENTIFY,
    MESSAGE_CONTENT,
    RECONNECT,
)
from tests.chat.conftest import DiscordHarness
from tests.chat.fake_discord import BOT_TOKEN, GATEWAY_URL, SteppedClock


async def _listening(harness: DiscordHarness) -> tuple[DiscordAdapter, str]:
    adapter = harness.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    return adapter, thread.id


async def test_identify_asks_for_message_content_and_the_owner_reply_arrives(
    discord_harness: DiscordHarness,
) -> None:
    adapter, thread_id = await _listening(discord_harness)
    await discord_harness.say(thread_id, Speaker.OWNER, "ship it")

    reply = await anext(adapter.replies())

    assert (reply.text, reply.author, reply.thread.id) == ("ship it", "Kostas", thread_id)
    (connection,) = discord_harness.gateway.connections
    assert connection.url == f"{GATEWAY_URL}/?v=10&encoding=json"
    identify = connection.sent[0]
    assert identify["op"] == IDENTIFY and identify["d"]["token"] == BOT_TOKEN
    assert identify["d"]["intents"] == GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT
    await adapter.close()


async def test_heartbeats_carry_the_last_sequence(
    discord_harness: DiscordHarness, stepped_clock: SteppedClock
) -> None:
    adapter, thread_id = await _listening(discord_harness)
    await discord_harness.say(thread_id, Speaker.OWNER, "hello")
    replies = adapter.replies()
    await anext(replies)

    await stepped_clock.sleeping(1)
    assert 0 <= stepped_clock.sleeps[0] <= 41.25
    stepped_clock.step()
    await stepped_clock.sleeping(2)

    (connection,) = discord_harness.gateway.connections
    beats = [payload for payload in connection.sent if payload["op"] == HEARTBEAT]
    assert beats == [{"op": HEARTBEAT, "d": 21}]
    assert stepped_clock.sleeps[1] == 41.25
    await adapter.close()


async def test_a_missing_heartbeat_ack_reconnects(
    discord_harness: DiscordHarness, stepped_clock: SteppedClock
) -> None:
    discord_harness.gateway.ack_heartbeats = False
    adapter, thread_id = await _listening(discord_harness)
    pending = asyncio.ensure_future(anext(adapter.replies()))

    await stepped_clock.sleeping(1)
    stepped_clock.step()  # first beat
    await stepped_clock.sleeping(2)
    stepped_clock.step()  # an interval passes without an ack
    await stepped_clock.sleeping(3)
    assert stepped_clock.sleeps[2] == 5.0
    stepped_clock.step()  # the reconnect delay
    await discord_harness.say(thread_id, Speaker.OWNER, "still there?")

    reply: Reply = await pending
    assert reply.text == "still there?"
    assert len(discord_harness.gateway.connections) == 2
    await adapter.close()


async def test_a_reconnect_request_opens_a_new_connection(
    discord_harness: DiscordHarness, stepped_clock: SteppedClock
) -> None:
    adapter, thread_id = await _listening(discord_harness)
    pending = asyncio.ensure_future(anext(adapter.replies()))
    discord_harness.gateway.events.put_nowait({"op": RECONNECT, "d": None, "s": None, "t": None})

    await stepped_clock.sleeping(2)  # the heartbeat jitter, then the reconnect delay
    stepped_clock.step(2)
    await discord_harness.say(thread_id, Speaker.OWNER, "back")

    assert (await pending).text == "back"
    assert len(discord_harness.gateway.connections) == 2
    await adapter.close()


async def test_a_fatal_close_code_stops_with_an_error_naming_it(
    discord_harness: DiscordHarness, stepped_clock: SteppedClock
) -> None:
    adapter, _ = await _listening(discord_harness)
    pending = asyncio.ensure_future(anext(adapter.replies()))
    await stepped_clock.sleeping(1)  # identified: the heartbeat waits for its first beat
    await discord_harness.gateway.connections[0].close(4014)

    with pytest.raises(ChatError, match="code 4014") as raised:
        await pending
    assert BOT_TOKEN not in str(raised.value)
    assert len(discord_harness.gateway.connections) == 1
