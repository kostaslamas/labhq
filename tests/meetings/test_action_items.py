"""An action item and its task are created together, or neither is (plan §6)."""

import pytest
from sqlalchemy import func, select

from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.db.models import MeetingActionItem, MeetingDecision, Task
from labhq.meetings import read_minutes, record
from labhq.work import WorkError
from tests.meetings.conftest import World


async def _count(world: World, model: type[object]) -> int:
    async with world.sessions() as db:
        return int(await db.scalar(select(func.count()).select_from(model)) or 0)


async def test_a_failure_creating_the_task_leaves_no_action_item(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_add_task(*args: object, **kwargs: object) -> Task:
        raise WorkError("the task store is down")

    monkeypatch.setattr(record, "add_task", failing_add_task)
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert (meeting.status, meeting.end_reason) == (MeetingStatus.FAILED, "minutes_not_recorded")
    assert await _count(world, MeetingActionItem) == 0
    assert await _count(world, MeetingDecision) == 0
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert [e.source for e in minutes.transcript].count(TranscriptSource.AGENT) == 3


async def test_a_failure_after_the_task_takes_the_task_back(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = record.add_task

    async def task_then_fail(*args: object, **kwargs: object) -> Task:
        await original(*args, **kwargs)  # type: ignore[arg-type]
        raise WorkError("failed after the task row")

    monkeypatch.setattr(record, "add_task", task_then_fail)
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    assert await _count(world, Task) == 0
    assert await _count(world, MeetingActionItem) == 0


async def test_every_action_item_has_its_task(world: World) -> None:
    world.stage.minutes.append(
        '{"decisions": ["A", "B"], "action_items": ['
        f'{{"title": "One", "assignee": {world.lead_id}, "decision": 2}}, '
        f'{{"title": "Two", "assignee": {world.manager_id}}}]}}'
    )
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    assert [(i.text, i.task_title, i.assignee_agent_id) for i in minutes.action_items] == [
        ("One", "One", world.lead_id),
        ("Two", "Two", world.manager_id),
    ]
    assert minutes.action_items[0].decision_id == minutes.decisions[1].id
    assert minutes.action_items[1].decision_id is None
    assert await _count(world, Task) == 2
