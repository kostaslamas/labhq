"""Meeting event listeners observe; one that raises never affects the meeting."""

from labhq.db.enums import MeetingStatus
from labhq.meetings import MeetingEvent, MeetingEventKind, default_listeners
from tests.meetings.conftest import World


def test_the_default_listener_registry_ships_empty() -> None:
    assert default_listeners.names() == []


async def test_listeners_see_start_entries_and_end(world: World) -> None:
    seen: list[MeetingEvent] = []

    async def record(event: MeetingEvent) -> None:
        seen.append(event)

    world.listeners.register("record", record)
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    kinds = [event.kind for event in seen]
    assert kinds[0] is MeetingEventKind.STARTED
    assert kinds[-1] is MeetingEventKind.ENDED
    assert kinds.count(MeetingEventKind.ENTRY_ADDED) == 3
    assert all(event.meeting_id == meeting_id for event in seen)


async def test_a_listener_that_raises_does_not_stop_the_meeting(world: World) -> None:
    calls = 0

    async def broken(event: MeetingEvent) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("discord is down")

    world.listeners.register("broken", broken)
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    assert calls == 5
