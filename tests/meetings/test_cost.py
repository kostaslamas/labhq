"""Meeting cost: the sum of its runs' cost events, counted by the project budget (plan §7)."""

from sqlalchemy import select, update

from labhq.budgets import Decision, check, spent_micros
from labhq.db.enums import BudgetScope, MeetingStatus, TranscriptSource
from labhq.db.models import CostEvent, Project
from labhq.meetings import meeting_cost_micros, read_minutes
from labhq.money import usd_to_micros
from tests.meetings.conftest import World


async def _set_budget(world: World, micros: int) -> None:
    async with world.sessions() as db:
        await db.execute(
            update(Project).where(Project.id == world.project_id).values(budget_micros=micros)
        )
        await db.commit()


async def test_the_meeting_cost_is_the_sum_of_its_turns_cost_events(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        run_ids = {e.run_id for e in minutes.transcript if e.run_id is not None}
        events = list(await db.scalars(select(CostEvent)))
        cost = await meeting_cost_micros(db, meeting_id)
    assert {event.run_id for event in events} == run_ids
    assert all(event.project_id == world.project_id for event in events)
    assert cost == sum(event.cost_micros for event in events)
    assert cost == 3 * usd_to_micros(world.stage.script.cost_usd or 0)
    assert minutes.cost_micros == cost


async def test_the_project_budget_check_counts_the_meeting(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    await world.service.start(meeting_id)

    async with world.sessions() as db:
        cost = await meeting_cost_micros(db, meeting_id)
        budget = await check(db, world.worker_id, world.clock)
        spent = await spent_micros(
            db, CostEvent.project_id == world.project_id, budget.period_start
        )
    project_level = next(level for level in budget.levels if level.scope is BudgetScope.PROJECT)
    assert cost > 0
    assert spent == cost
    assert project_level.spent_micros == cost


async def test_at_full_project_budget_no_further_turn_starts(world: World) -> None:
    per_run = usd_to_micros(world.stage.script.cost_usd or 0)
    # One turn exhausts the budget: the second participant never speaks.
    await _set_budget(world, per_run)
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert (meeting.status, meeting.end_reason) == (MeetingStatus.ENDED, "budget")
    assert len(world.stage.prompts) == 1
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        decision = (await check(db, world.manager_id, world.clock)).decision
    assert [e.source for e in minutes.transcript] == [
        TranscriptSource.AGENT,
        TranscriptSource.SYSTEM,
    ]
    assert minutes.decisions == ()
    assert decision is Decision.STOP


async def test_a_spent_budget_stops_the_meeting_before_its_first_turn(world: World) -> None:
    await _set_budget(world, 0)
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert (meeting.status, meeting.end_reason) == (MeetingStatus.ENDED, "budget")
    assert world.stage.prompts == []
