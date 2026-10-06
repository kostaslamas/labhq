"""The CEO's heartbeat: one timer wakeup per period, briefed with what changed."""

from datetime import timedelta

from sqlalchemy import select

from labhq.autonomy import AutonomySettings
from labhq.autonomy.heartbeat import NOTHING_NEW, heartbeat_pass
from labhq.db.enums import ApprovalStatus, RiskClass, TaskStatus, WakeupSource
from labhq.db.models import Approval, Comment, Run, Task, WakeupRequest
from tests.autonomy.conftest import HEARTBEAT, SETTINGS, World


async def _pass(world: World, settings: AutonomySettings = SETTINGS) -> list[int]:
    return await heartbeat_pass(world.sessions, world.clock, world.scheduler.enqueue, settings)


async def _timers(world: World) -> list[WakeupRequest]:
    async with world.sessions() as db:
        return list(
            await db.scalars(
                select(WakeupRequest)
                .where(WakeupRequest.source == WakeupSource.TIMER)
                .order_by(WakeupRequest.id)
            )
        )


async def test_the_ceo_gets_exactly_one_timer_wakeup_per_interval(
    world: World, ceo_id: int
) -> None:
    assert await _pass(world) == [ceo_id]
    assert await _pass(world) == []
    world.clock.advance(HEARTBEAT // 2)
    assert await _pass(world) == []
    assert len(await _timers(world)) == 1

    # An unconsumed heartbeat absorbs the next one, so let the CEO take its turn first.
    await world.scheduler.tick()
    await world.scheduler.settle()
    world.clock.advance(HEARTBEAT)
    assert await _pass(world) == [ceo_id]
    assert [w.agent_id for w in await _timers(world)] == [ceo_id, ceo_id]


async def test_a_heartbeat_of_zero_never_wakes_the_ceo(world: World, ceo_id: int) -> None:
    off = AutonomySettings(ceo_heartbeat_seconds=0)

    for _ in range(3):
        assert await _pass(world, off) == []
        world.clock.advance(HEARTBEAT)

    assert await _timers(world) == []


async def test_the_brief_lists_only_what_changed_since_the_last_turn(
    world: World, ceo_id: int
) -> None:
    now = world.clock.now()
    async with world.sessions() as db:
        old, fresh = (
            Task(
                project_id=world.project_id,
                title=title,
                status=TaskStatus.IN_REVIEW,
                created_at=now,
                updated_at=now,
            )
            for title in ("Old report", "Fresh report")
        )
        db.add_all([old, fresh])
        await db.flush()
        db.add(Run(agent_id=ceo_id, adapter="fake", created_at=now + timedelta(minutes=10)))
        for task, offset in ((old, 5), (fresh, 15)):
            db.add(
                Comment(
                    task_id=task.id,
                    author_agent_id=world.agent_id,
                    body="done",
                    created_at=now + timedelta(minutes=offset),
                )
            )
        for created, kind in ((5, "old_action"), (15, "fresh_action")):
            db.add(
                Approval(
                    type=kind,
                    risk_class=RiskClass.LIGHT,
                    status=ApprovalStatus.PENDING,
                    payload={},
                    created_at=now + timedelta(minutes=created),
                )
            )
        await db.commit()
    world.clock.advance(timedelta(minutes=30))

    await _pass(world)

    (wakeup,) = await _timers(world)
    assert "Fresh report" in wakeup.reason and "fresh_action" in wakeup.reason
    assert "Old report" not in wakeup.reason and "old_action" not in wakeup.reason


async def test_a_quiet_organisation_gets_a_one_line_brief(world: World, ceo_id: int) -> None:
    await _pass(world)

    (wakeup,) = await _timers(world)
    assert wakeup.reason == NOTHING_NEW
