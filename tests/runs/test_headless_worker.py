"""A headless worker resumes its task's session and leaves no process behind (#190)."""

from labhq.db.models import Task
from tests.runs.conftest import World
from tests.runs.helpers import task_sessions


async def test_the_same_task_resumes_its_session_and_a_new_task_starts_fresh(
    world: World,
) -> None:
    async with world.sessions() as db:
        other = Task(
            project_id=world.project_id,
            title="Second task",
            created_at=world.clock.now(),
            updated_at=world.clock.now(),
        )
        db.add(other)
        await db.commit()
        other_id = other.id

    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="start")
    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="again")
    await world.service.execute(agent_id=world.agent_id, task_id=other_id, prompt="elsewhere")

    assert [request.resume_session_id for request in world.fake.requests] == [
        None,
        "fake-session-1",
        None,
    ]
    assert {row.task_id for row in await task_sessions(world)} == {world.task_id, other_id}


async def test_no_process_remains_after_a_turn(world: World) -> None:
    assert world.fake.live_processes == 0

    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="start")
    assert world.fake.live_processes == 0

    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="again")
    assert (world.fake.requests.__len__(), world.fake.closes, world.fake.live_processes) == (
        2,
        2,
        0,
    )
