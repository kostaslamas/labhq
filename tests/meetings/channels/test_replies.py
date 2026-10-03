"""The owner's replies in a meeting thread become owner entries, once each."""

from labhq.adapters import RunRequest
from labhq.chat import Channel, Thread
from labhq.db.enums import TranscriptSource
from labhq.meetings import read_minutes
from labhq.meetings.channels.inbound import receive
from tests.meetings.channels.conftest import ADAPTER, Bridge


async def test_a_reply_delivered_twice_is_recorded_once_and_reaches_the_next_turn(
    bridge: Bridge,
) -> None:
    world = bridge.world
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    recorded = []

    async def owner_replies_in_the_thread(_request: RunRequest) -> None:
        await bridge.flush()
        if len(world.stage.prompts) != 1:
            return
        thread = await bridge.thread_of(meeting_id)
        reply = bridge.reply(thread, "Prioritise the login bug.", "msg-1")
        for _delivery in range(2):
            recorded.append(
                await receive(
                    world.sessions, world.clock, ADAPTER, reply, listeners=world.listeners
                )
            )

    world.stage.on_start.append(owner_replies_in_the_thread)
    await world.service.start(meeting_id)

    assert recorded[0] is not None
    assert recorded[1] is None
    first, second = world.stage.turn_prompts()
    assert "Prioritise the login bug." not in first
    assert "[Owner] Prioritise the login bug." in second
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    owner = [e for e in minutes.transcript if e.source is TranscriptSource.OWNER]
    assert [(e.text, e.external_ref) for e in owner] == [("Prioritise the login bug.", "msg-1")]
    # The reply is already in the thread; mirroring it back would repeat it.
    await bridge.flush()
    texts = [text for _, text in bridge.posts((await bridge.thread_of(meeting_id)).id)]
    assert "Prioritise the login bug." not in texts


async def test_a_reply_in_a_thread_of_no_meeting_is_ignored(bridge: Bridge) -> None:
    world = bridge.world
    thread = Thread(Channel("infra", "1"), "999")

    entry = await receive(
        world.sessions,
        world.clock,
        ADAPTER,
        bridge.reply(thread, "hi", "m"),
        listeners=world.listeners,
    )

    assert entry is None


async def test_a_reply_after_the_meeting_closed_is_not_recorded(bridge: Bridge) -> None:
    world = bridge.world
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    await world.service.start(meeting_id)
    await bridge.flush()
    thread = await bridge.thread_of(meeting_id)

    entry = await receive(
        world.sessions,
        world.clock,
        ADAPTER,
        bridge.reply(thread, "late", "m9"),
        listeners=world.listeners,
    )

    assert entry is None
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert all(e.source is not TranscriptSource.OWNER for e in minutes.transcript)
