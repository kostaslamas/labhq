"""Last activity is the later of the latest `run_events` row and the last screen change."""

from datetime import timedelta

import pytest
from sqlalchemy import update

from labhq.callcenter.status import status_freshness
from labhq.db.enums import RunStatus
from labhq.db.models import Run, RunEvent
from tests.callcenter.screens.conftest import Office

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")


async def test_a_capture_reads_the_managers_pane_and_sends_it_nothing(office: Office) -> None:
    async with office.sessions() as db:
        screen = await office.reader.capture(db, office.clock, agent_id=office.manager_id)

    assert screen is not None
    assert (screen.run_id, screen.agent_id) == (office.run_id, office.manager_id)
    assert "manager: working on the login form" in screen.text
    assert office.server.keys_sent() == []
    assert "received:" not in office.screen()


async def test_a_screen_seen_first_is_as_old_as_the_runs_last_event(office: Office) -> None:
    async with office.sessions() as db:
        screen = await office.reader.capture(db, office.clock, agent_id=office.manager_id)
        freshness = await status_freshness(
            db, office.clock, office.manager_id, screens=office.reader
        )

    assert screen is not None
    assert screen.changed_at == office.clock.now() - timedelta(minutes=1)
    assert freshness.fresh
    assert freshness.screen is not None


async def test_a_screen_change_after_the_latest_status_makes_it_stale(office: Office) -> None:
    async with office.sessions() as db:
        before = await status_freshness(db, office.clock, office.manager_id, screens=office.reader)
    office.clock.advance(timedelta(minutes=2))
    await office.progress("manager: tests pass, opening the pull request")

    async with office.sessions() as db:
        after = await status_freshness(db, office.clock, office.manager_id, screens=office.reader)
        # Without the screen, the run's events alone still call the status fresh.
        events_only = await status_freshness(db, office.clock, office.manager_id)

    assert before.fresh
    assert not after.fresh
    assert after.screen is not None
    assert after.screen.changed_at == office.clock.now()
    assert "opening the pull request" in after.screen.text
    assert after.age == timedelta(minutes=2)
    assert events_only.fresh
    assert office.server.keys_sent() == []


async def test_an_unchanged_screen_keeps_its_time_and_the_status_fresh(office: Office) -> None:
    async with office.sessions() as db:
        first = await office.reader.capture(db, office.clock, agent_id=office.manager_id)
        office.clock.advance(timedelta(minutes=5))
        second = await office.reader.capture(db, office.clock, agent_id=office.manager_id)
        freshness = await status_freshness(
            db, office.clock, office.manager_id, screens=office.reader
        )

    assert first is not None and second is not None
    assert second.changed_at == first.changed_at
    assert freshness.fresh


async def test_a_task_finds_the_pane_of_the_agent_running_on_it(office: Office) -> None:
    async with office.sessions() as db:
        screen = await office.reader.capture(db, office.clock, task_id=office.task_id)

    assert screen is not None and screen.agent_id == office.manager_id


async def test_an_ended_run_has_no_pane_and_is_judged_on_its_events(office: Office) -> None:
    async with office.sessions() as db:
        await db.execute(
            update(Run).where(Run.id == office.run_id).values(status=RunStatus.SUCCEEDED)
        )
        office.clock.advance(timedelta(minutes=3))
        db.add(RunEvent(run_id=office.run_id, seq=2, kind="result", created_at=office.clock.now()))
        await db.commit()
        office.clock.advance(timedelta(minutes=1))
        freshness = await status_freshness(
            db, office.clock, office.manager_id, screens=office.reader
        )

    assert freshness.screen is None
    assert not freshness.fresh
    assert freshness.age == timedelta(minutes=4)


async def test_an_sdk_agent_has_no_pane(office: Office) -> None:
    async with office.sessions() as db:
        await db.execute(update(Run).where(Run.id == office.run_id).values(adapter="claude"))
        await db.commit()
        screen = await office.reader.capture(db, office.clock, agent_id=office.manager_id)

    assert screen is None
