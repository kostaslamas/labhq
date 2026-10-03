"""Meeting kinds are data; participants come from the kind unless a list overrides them."""

import pytest

from labhq.db.enums import MeetingStatus
from labhq.meetings import MeetingError, MeetingKind, default_kinds, read_minutes
from tests.meetings.conftest import World


def test_the_three_phase_3_kinds_are_registered() -> None:
    assert list(default_kinds) == ["planning", "review", "standup"]


def test_a_kind_needs_a_round() -> None:
    with pytest.raises(ValueError, match="at least one round"):
        MeetingKind("empty", "Agenda", frozenset({"manager"}), 0, "Minutes.")


async def test_a_new_kind_is_a_registration(world: World) -> None:
    world.kinds.register(
        "retro",
        MeetingKind(
            key="retro",
            agenda="Retro for {project}.",
            participant_roles=frozenset({"manager", "worker"}),
            rounds=2,
            minutes_instruction="One decision per lesson.",
        ),
    )
    world.stage.minutes.append(
        world.minutes_json().replace(str(world.lead_id), str(world.worker_id))
    )

    meeting_id = await world.approved_meeting("retro")
    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    assert meeting.agenda == "Retro for demo."
    # Two participants, two rounds.
    assert len(world.stage.turn_prompts()) == 4
    assert "Round 2 of 2" in world.stage.turn_prompts()[-1]
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert {p.agent_id for p in minutes.participants} == {world.manager_id, world.worker_id}


async def test_an_explicit_participant_list_overrides_the_kind(world: World) -> None:
    world.stage.minutes.append(
        world.minutes_json().replace(str(world.lead_id), str(world.worker_id))
    )
    meeting_id = await world.approved_meeting(participants=[world.worker_id])

    await world.service.start(meeting_id)

    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert [p.agent_id for p in minutes.participants] == [world.worker_id]
    assert (await world.meeting(meeting_id)).facilitator_agent_id == world.worker_id


async def test_an_unknown_participant_is_refused(world: World) -> None:
    with pytest.raises(MeetingError, match="no agents"):
        await world.service.request(project_id=world.project_id, kind="standup", participants=[999])
