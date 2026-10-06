"""With autonomy paused nothing starts on its own, but the owner can still reach the CEO."""

from labhq.autonomy import Autonomy, set_autonomy
from labhq.autonomy.heartbeat import heartbeat_pass
from labhq.db.enums import WakeupSource
from labhq.scheduler import Wakeup
from tests.autonomy.conftest import SETTINGS, World
from tests.scheduler.helpers import on_task, runs


async def _pause(world: World) -> None:
    async with world.sessions() as db:
        await set_autonomy(db, world.clock, Autonomy.PAUSED)


async def test_paused_autonomy_holds_automatic_wakeups_and_resumes(world: World) -> None:
    await world.scheduler.enqueue(on_task(world, "assigned"))
    await _pause(world)

    report = await world.scheduler.tick()

    assert report.started == []
    assert await runs(world) == []

    async with world.sessions() as db:
        await set_autonomy(db, world.clock, Autonomy.ON)
    assert len((await world.scheduler.tick()).started) == 1


async def test_an_owner_message_still_reaches_the_ceo_while_paused(
    world: World, ceo_id: int
) -> None:
    await _pause(world)
    await world.scheduler.enqueue(on_task(world, "assigned"))
    await world.scheduler.enqueue(
        Wakeup(
            agent_id=ceo_id,
            source=WakeupSource.OWNER_MESSAGE,
            idempotency_key="owner:1",
            reason="Status?",
        )
    )

    report = await world.scheduler.tick()

    started = [run for run in await runs(world) if run.id in report.started]
    assert [run.agent_id for run in started] == [ceo_id]


async def test_paused_autonomy_enqueues_no_heartbeat(world: World, ceo_id: int) -> None:
    await _pause(world)

    woken = await heartbeat_pass(world.sessions, world.clock, world.scheduler.enqueue, SETTINGS)

    assert woken == []


async def test_the_environment_sets_the_start_up_value(world: World) -> None:
    from labhq.autonomy import AutonomySettings, get_autonomy

    paused = AutonomySettings(autonomy=Autonomy.PAUSED)
    async with world.sessions() as db:
        assert await get_autonomy(db, paused) is Autonomy.PAUSED
        await set_autonomy(db, world.clock, Autonomy.ON)
        assert await get_autonomy(db, paused) is Autonomy.ON
