"""Invariants the database enforces on its own, whatever the engine code does."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import RunStatus, WakeupSource
from labhq.db.models import HealthRule, Host, Incident, Run, Task, WakeupRequest
from tests.db.factories import project_agent_task, run_for


async def test_duplicate_idempotency_key_is_rejected(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, _ = await project_agent_task(session, clock)
    now = clock.now()
    for _ in range(2):
        session.add(
            WakeupRequest(
                agent_id=agent.id,
                source=WakeupSource.TIMER,
                idempotency_key="timer:agent-1:2026-10-02T09:00",
                created_at=now,
                updated_at=now,
            )
        )
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.flush()


async def test_checkout_run_id_must_reference_an_existing_run(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, _, task = await project_agent_task(session, clock)
    await session.commit()
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        await session.execute(update(Task).where(Task.id == task.id).values(checkout_run_id=999))
        await session.commit()


async def test_conditional_checkout_lets_only_the_first_run_through(
    session: AsyncSession, clock: FakeClock
) -> None:
    # The shape the scheduler uses; here it only proves the column supports it.
    _, agent, task = await project_agent_task(session, clock)
    first, second = (
        await run_for(session, clock, agent, task),
        await run_for(session, clock, agent, task),
    )
    claims = []
    for run in (first, second):
        result = await session.execute(
            update(Task)
            .where(Task.id == task.id, Task.checkout_run_id.is_(None))
            .values(checkout_run_id=run.id)
        )
        claims.append(result.rowcount)  # type: ignore[attr-defined]
    assert claims == [1, 0]
    assert (await session.scalar(select(Task.checkout_run_id))) == first.id


async def test_status_outside_the_vocabulary_is_rejected_by_the_database(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    run = await run_for(session, clock, agent, task)
    await session.commit()
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        await session.execute(
            text("UPDATE runs SET status = 'exploded' WHERE id = :id"), {"id": run.id}
        )


async def test_run_statuses_are_the_phase_1_vocabulary() -> None:
    assert [status.value for status in RunStatus] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "interrupted",
        "timed_out",
    ]


async def test_timestamps_round_trip_as_aware_utc(session: AsyncSession, clock: FakeClock) -> None:
    _, agent, task = await project_agent_task(session, clock)
    run = await run_for(session, clock, agent, task)
    run.heartbeat_at = datetime(2026, 10, 2, 12, 30, tzinfo=timezone(timedelta(hours=3)))
    await session.commit()
    row = (
        await session.execute(select(Run.heartbeat_at, Run.created_at).where(Run.id == run.id))
    ).one()
    assert row.heartbeat_at == datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
    assert row.heartbeat_at.tzinfo is UTC
    assert row.created_at == clock.now()


async def test_naive_timestamps_are_refused(session: AsyncSession, clock: FakeClock) -> None:
    _, agent, task = await project_agent_task(session, clock)
    run = await run_for(session, clock, agent, task)
    run.heartbeat_at = datetime(2026, 10, 2, 9, 30)  # noqa: DTZ001
    with pytest.raises(StatementError, match="naive datetime"):
        await session.flush()


async def test_one_open_incident_per_rule_and_host(session: AsyncSession, clock: FakeClock) -> None:
    now = clock.now()
    host = Host(name="local", is_local=True, created_at=now, updated_at=now)
    rule = HealthRule(
        type="threshold",
        name="disk",
        reason="disk fills up",
        created_by="test",
        created_at=now,
        updated_at=now,
    )
    session.add_all([host, rule])
    await session.flush()
    first = Incident(rule_id=rule.id, host_id=host.id, opened_at=now)
    session.add(first)
    await session.flush()
    session.add(Incident(rule_id=rule.id, host_id=host.id, opened_at=now))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.flush()
    await session.rollback()


async def test_a_resolved_incident_allows_a_new_one(
    session: AsyncSession, clock: FakeClock
) -> None:
    now = clock.now()
    host = Host(name="local", is_local=True, created_at=now, updated_at=now)
    rule = HealthRule(
        type="threshold", name="cpu", reason="r", created_by="test", created_at=now, updated_at=now
    )
    session.add_all([host, rule])
    await session.flush()
    session.add(
        Incident(
            rule_id=rule.id, host_id=host.id, status="resolved", opened_at=now, resolved_at=now
        )
    )
    session.add(Incident(rule_id=rule.id, host_id=host.id, opened_at=now))
    await session.flush()
