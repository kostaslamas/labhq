"""`meeting_minutes`: the minutes in spoken sentences, and picking the meeting from speech."""

import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.minutes import meeting_minutes, meeting_ref
from labhq.clock import FakeClock
from labhq.db.enums import MeetingStatus
from labhq.db.models import MeetingActionItem, Run
from labhq.meetings import meeting_cost_micros
from labhq.speech import say_micros, speakable
from tests.callcenter.answers.minutes_seed import Team, add_meeting, add_team
from tests.meetings.conftest import World, sessions, world

# The meeting tests' fixtures, so a standup runs through #73's own service.
__all__ = ["sessions", "world"]

BUDGET_SECONDS = 2.0


def assert_spoken(text: str) -> None:
    assert speakable(text) == text
    assert "|" not in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


@pytest.fixture
async def demo(session: AsyncSession, clock: FakeClock) -> Team:
    return await add_team(session, clock.now(), "demo")


@pytest.fixture
async def beta(session: AsyncSession, clock: FakeClock) -> Team:
    return await add_team(session, clock.now(), "beta")


async def test_a_finished_standup_reads_its_decisions_and_action_items(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()
    await world.service.start(meeting_id)

    async with world.sessions() as db:
        text = await meeting_minutes(db, world.clock, "this morning's standup")
        task_id = await db.scalar(
            select(MeetingActionItem.task_id).where(MeetingActionItem.meeting_id == meeting_id)
        )
        cost = await meeting_cost_micros(db, meeting_id)

    assert_spoken(text)
    assert text.startswith("The standup for demo ended")
    assert "Manager and Backend lead took part." in text
    assert "One decision was recorded. Decision 1: Ship the parser first." in text
    assert f"Write parser tests, assigned to Backend lead. Task T{task_id} is" in text
    # The fake adapter reports a cost for every turn; the meeting's sum is said aloud.
    assert cost > 0
    assert text.endswith(f"It cost {say_micros(cost)}.")


async def test_with_no_meeting_the_answer_says_so(session: AsyncSession, clock: FakeClock) -> None:
    assert await meeting_minutes(session, clock) == "No meeting has been held yet."


async def test_nothing_named_reads_the_latest_meeting_of_any_project(
    session: AsyncSession, clock: FakeClock, demo: Team, beta: Team
) -> None:
    now = clock.now()
    await add_meeting(session, demo, now - timedelta(hours=2), decisions=["Old one"])
    await add_meeting(session, beta, now - timedelta(hours=1), kind="review", decisions=["New"])

    for said in (None, "", "the last meeting"):
        text = await meeting_minutes(session, clock, said)
        assert text.startswith("The review for beta ended 1 hour ago."), said


async def test_the_last_planning_of_a_project_picks_that_project_and_kind(
    session: AsyncSession, clock: FakeClock, demo: Team, beta: Team
) -> None:
    now = clock.now()
    await add_meeting(session, beta, now - timedelta(days=3), kind="planning", decisions=["Old"])
    await add_meeting(session, beta, now - timedelta(days=1), kind="planning", decisions=["Pick"])
    await add_meeting(session, beta, now - timedelta(hours=1), decisions=["A standup"])
    await add_meeting(session, demo, now, kind="planning", decisions=["Other project"])

    text = await meeting_minutes(session, clock, "the last planning of project beta")

    assert text.startswith("The planning for beta ended 1 day ago.")
    assert "Decision 1: Pick." in text


async def test_two_standups_this_morning_get_a_question_back(
    session: AsyncSession, clock: FakeClock, demo: Team, beta: Team
) -> None:
    now = clock.now()
    first = await add_meeting(session, demo, now - timedelta(hours=2))
    second = await add_meeting(session, beta, now - timedelta(hours=1))

    text = await meeting_minutes(session, clock, "this morning's standup")

    assert_spoken(text)
    assert text.startswith("2 standups fit.")
    assert f"Meeting {meeting_ref(second)} is the standup for beta, 1 hour ago." in text
    assert f"Meeting {meeting_ref(first)} is the standup for demo, 2 hours ago." in text
    assert text.endswith("Which one? Say the meeting number or the project.")
    assert "Ship the parser first" not in text


async def test_the_owner_answers_the_question_with_a_project_or_a_number(
    session: AsyncSession, clock: FakeClock, demo: Team, beta: Team
) -> None:
    now = clock.now()
    first = await add_meeting(session, demo, now - timedelta(hours=2))
    await add_meeting(session, beta, now - timedelta(hours=1))

    by_project = await meeting_minutes(session, clock, "this morning's standup for demo")
    by_number = await meeting_minutes(session, clock, meeting_ref(first))
    spelled = await meeting_minutes(session, clock, f"meeting number {first}")

    assert by_project.startswith("The standup for demo ended 2 hours ago.")
    assert by_number == by_project == spelled


async def test_two_meetings_of_one_project_on_a_named_day_also_get_a_question(
    session: AsyncSession, clock: FakeClock, demo: Team
) -> None:
    now = clock.now()
    await add_meeting(session, demo, now - timedelta(hours=3))
    await add_meeting(session, demo, now - timedelta(hours=1))

    assert (await meeting_minutes(session, clock, "this morning's standup")).startswith("2 ")
    latest = await meeting_minutes(session, clock, "this morning's last standup")
    assert latest.startswith("The standup for demo ended 1 hour ago.")


async def test_a_day_phrase_keeps_meetings_of_other_days_out(
    session: AsyncSession, clock: FakeClock, demo: Team
) -> None:
    now = clock.now()
    await add_meeting(session, demo, now - timedelta(days=1), kind="review", decisions=["Then"])
    await add_meeting(session, demo, now - timedelta(hours=1), kind="review", decisions=["Now"])

    yesterday = await meeting_minutes(session, clock, "yesterday's review")
    assert "Decision 1: Then." in yesterday
    assert "Decision 1: Now." in await meeting_minutes(session, clock, "today's review")
    nothing = await meeting_minutes(session, clock, "this morning's planning")
    assert nothing == "I found no planning this morning."


async def test_an_unknown_meeting_number_is_said_back(
    session: AsyncSession, clock: FakeClock
) -> None:
    assert await meeting_minutes(session, clock, "M99") == "I have no meeting M99."


async def test_a_running_meeting_has_no_minutes_yet(
    session: AsyncSession, clock: FakeClock, demo: Team
) -> None:
    await add_meeting(
        session, demo, clock.now(), status=MeetingStatus.RUNNING, decisions=[], items=[]
    )

    text = await meeting_minutes(session, clock)

    assert text.startswith("The standup for demo is still running. It started just now.")
    assert "Its minutes are not written yet." in text


async def test_unspeakable_minutes_are_flattened_and_long_ones_are_cut(
    session: AsyncSession, clock: FakeClock, demo: Team
) -> None:
    decisions = ['| a | table | {"json": [1, 2]}', *(f"Decision text {n}" for n in range(7))]
    await add_meeting(
        session, demo, clock.now(), decisions=decisions, items=["# Heading", "- a list item"]
    )

    text = await meeting_minutes(session, clock)

    assert_spoken(text)
    assert "8 decisions were recorded." in text
    assert "3 more decisions are in the minutes." in text
    assert "2 action items were recorded." in text


async def test_the_cost_is_said_in_dollars_and_cents(
    session: AsyncSession, clock: FakeClock, demo: Team
) -> None:
    await add_meeting(session, demo, clock.now(), cost_micros=1_230_000)

    assert "It cost 1 dollar and 23 cents." in await meeting_minutes(session, clock)


async def test_it_answers_within_two_seconds_and_starts_no_agent(
    session: AsyncSession, clock: FakeClock, demo: Team, beta: Team
) -> None:
    start = clock.now() - timedelta(days=200)
    for n in range(400):
        team = demo if n % 2 else beta
        await add_meeting(session, team, start + timedelta(hours=12 * n))
    runs = await session.scalar(select(func.count()).select_from(Run))

    for said in (None, "this morning's standup", "the last standup of demo", "yesterday"):
        started = time.perf_counter()
        await meeting_minutes(session, clock, said)
        elapsed = time.perf_counter() - started
        assert elapsed < BUDGET_SECONDS, f"{said!r} took {elapsed:.2f}s"
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(Run)) == runs
