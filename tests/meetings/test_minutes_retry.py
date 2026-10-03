"""Invalid minutes JSON gets one retry; then the meeting fails and keeps its transcript."""

from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.meetings import read_minutes
from tests.meetings.conftest import World


async def test_invalid_minutes_are_retried_once(world: World) -> None:
    world.stage.minutes.extend(["Minutes: we agreed things.", world.minutes_json()])
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    first, retry = world.stage.minutes_prompts()
    assert "previous reply was not valid minutes" not in first
    assert "previous reply was not valid minutes" in retry


async def test_twice_invalid_minutes_fail_the_meeting_and_keep_the_transcript(
    world: World,
) -> None:
    world.stage.minutes.extend(["not json", '{"decisions": "one"}', world.minutes_json()])
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert (meeting.status, meeting.end_reason) == (MeetingStatus.FAILED, "invalid_minutes")
    assert meeting.ended_at is not None
    assert len(world.stage.minutes_prompts()) == 2
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert minutes.decisions == ()
    assert minutes.action_items == ()
    turns = [e.text for e in minutes.transcript if e.source is TranscriptSource.AGENT]
    assert turns[:2] == [
        "turn 1: done the parser, next the tests, no blockers",
        "turn 2: done the parser, next the tests, no blockers",
    ]
    assert minutes.transcript[-1].source is TranscriptSource.SYSTEM


async def test_an_assignee_outside_the_meeting_is_invalid_minutes(world: World) -> None:
    outsider = world.minutes_json().replace(f'"assignee": {world.lead_id}', '"assignee": 999')
    world.stage.minutes.extend([outsider, world.minutes_json()])
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    assert "not a participant" in world.stage.minutes_prompts()[1]


async def test_a_facilitator_with_no_reply_counts_as_invalid(world: World) -> None:
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.FAILED
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    silent = [e for e in minutes.transcript if "did not reply" in e.text]
    assert len(silent) == 2
    assert all(entry.run_id is not None for entry in silent)
