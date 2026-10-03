"""With the chat service down the meeting completes; the backlog follows, in order."""

from datetime import timedelta

from labhq.callcenter.answers.minutes import meeting_minutes
from labhq.db.enums import MeetingStatus
from labhq.meetings import read_minutes
from tests.meetings.channels.conftest import Bridge


async def test_a_meeting_completes_with_the_adapter_down_and_the_backlog_follows(
    bridge: Bridge,
) -> None:
    world = bridge.world
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    bridge.adapter.down = True

    async def try_to_mirror(_request: object) -> None:
        assert await bridge.flush() == 0

    world.stage.on_start.append(try_to_mirror)
    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    assert bridge.service.posts == {}
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        spoken = await meeting_minutes(db, world.clock, f"meeting {meeting_id}")
    assert len(minutes.transcript) == 3
    assert [d.text for d in minutes.decisions] == ["Ship the parser first"]
    assert len(minutes.action_items) == 1
    assert "Ship the parser first" in spoken
    pending = await bridge.outbox()
    # Only the head of the queue was tried; nothing behind it was touched.
    assert pending[0].attempts >= 1
    assert all(post.attempts == 0 for post in pending[1:])

    bridge.adapter.down = False
    world.clock.advance(timedelta(seconds=bridge.settings.retry_max_seconds))
    sent = await bridge.flush()

    assert sent == len(pending)
    thread = await bridge.thread_of(meeting_id)
    texts = [text for _, text in bridge.posts(thread.id)]
    assert texts == [post.text for post in pending]
    assert texts[1:4] == [entry.text for entry in minutes.transcript]
    assert texts[-1].startswith(f"Minutes of standup M{meeting_id}")
    assert len(bridge.service.threads) == 1


async def test_a_failed_post_backs_off_doubling_up_to_the_cap(bridge: Bridge) -> None:
    world = bridge.world
    meeting_id = await world.approved_meeting()
    world.stage.minutes.append(world.minutes_json())
    await world.service.start(meeting_id)
    bridge.adapter.down = True
    delays = []
    for _attempt in range(8):
        await bridge.flush()
        head = (await bridge.outbox())[0]
        assert head.next_attempt_at is not None
        delays.append((head.next_attempt_at - world.clock.now()).total_seconds())
        world.clock.advance(timedelta(seconds=bridge.settings.retry_max_seconds))

    base = bridge.settings.retry_base_seconds
    cap = bridge.settings.retry_max_seconds
    # The ticking clock moves a second on each read, so each delay reads a second short.
    expected = [min(base * 2**n, cap) - 1 for n in range(8)]
    assert delays == expected
    assert head.last_error == "ChatError: service unavailable"
