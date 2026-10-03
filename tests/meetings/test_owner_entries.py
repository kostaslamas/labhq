"""Owner entries join the transcript and reach the next turns."""

import pytest

from labhq.adapters import RunRequest
from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.meetings import MeetingClosedError, add_owner_entry, read_minutes
from tests.meetings.conftest import World


async def test_an_owner_entry_added_during_the_meeting_reaches_the_next_turn(
    world: World,
) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    async def owner_speaks_during_the_first_turn(request: RunRequest) -> None:
        if len(world.stage.prompts) == 1:
            await add_owner_entry(
                world.sessions,
                world.clock,
                meeting_id=meeting_id,
                text="Prioritise the login bug.",
                external_ref="discord:msg:1",
                listeners=world.listeners,
            )

    world.stage.on_start.append(owner_speaks_during_the_first_turn)

    await world.service.start(meeting_id)

    first, second = world.stage.turn_prompts()
    assert "Prioritise the login bug." not in first
    assert "[Owner] Prioritise the login bug." in second
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    owner = [e for e in minutes.transcript if e.source is TranscriptSource.OWNER]
    assert [(e.speaker, e.run_id, e.external_ref) for e in owner] == [
        ("Owner", None, "discord:msg:1")
    ]
    assert [p.agent_id for p in minutes.participants].count(None) == 1


async def test_a_mirrored_message_is_recorded_once(world: World) -> None:
    meeting = await world.service.request(project_id=world.project_id, kind="standup")

    first = await add_owner_entry(
        world.sessions, world.clock, meeting_id=meeting.id, text="hi", external_ref="m1"
    )
    again = await add_owner_entry(
        world.sessions, world.clock, meeting_id=meeting.id, text="hi", external_ref="m1"
    )

    assert first is not None
    assert again is None
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting.id)
    assert len(minutes.transcript) == 1


async def test_a_closed_meeting_takes_no_owner_entry(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    meeting = await world.service.start(meeting_id)
    assert meeting.status is MeetingStatus.ENDED

    with pytest.raises(MeetingClosedError):
        await add_owner_entry(world.sessions, world.clock, meeting_id=meeting_id, text="late")
