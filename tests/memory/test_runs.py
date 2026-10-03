from pathlib import Path

from sqlalchemy import select

from labhq.adapters import AdapterError
from labhq.db.enums import RunStatus
from labhq.db.models import RunEvent
from labhq.memory import MEMORY_CONFIG_KEY, MEMORY_HEADING, MEMORY_RELATIVE_PATH
from labhq.runs.lifecycle import MEMORY_EVENT
from tests.memory.conftest import MemoryWorld, write_memory

NOTE = "Owner wants the release on Friday. Lead 7 owns the parser."


async def event_kinds(world: MemoryWorld, run_id: int) -> list[str]:
    async with world.sessions() as db:
        rows = await db.scalars(select(RunEvent).where(RunEvent.run_id == run_id))
        return [row.kind for row in sorted(rows, key=lambda row: row.seq)]


async def test_a_managers_memory_from_one_run_is_in_the_next_runs_prompt(
    world: MemoryWorld,
) -> None:
    manager = await world.agent("manager")

    first = await world.run(manager, writes=NOTE)
    assert world.last_cwd() == world.memory.home(manager)
    assert MEMORY_HEADING in world.last_prompt()
    assert NOTE not in world.last_prompt()
    assert MEMORY_EVENT in await event_kinds(world, first.run_id)

    await world.run(manager)
    assert NOTE in world.last_prompt()
    assert world.last_prompt().endswith("Do the work.")
    assert world.memory.read(manager) == NOTE


async def test_a_leads_memory_follows_it_across_tasks_and_worktrees(
    world: MemoryWorld, tmp_path: Path
) -> None:
    lead = await world.agent("lead")
    first_tree, second_tree = tmp_path / "tree-1", tmp_path / "tree-2"
    first_tree.mkdir()
    second_tree.mkdir()

    await world.run(lead, task_id=world.task_ids[0], cwd=first_tree, writes=NOTE)
    await world.run(lead, task_id=world.task_ids[1], cwd=second_tree)

    assert world.last_cwd() == second_tree
    assert NOTE in world.last_prompt()
    assert (second_tree / MEMORY_RELATIVE_PATH).read_text(encoding="utf-8") == NOTE


async def test_a_fresh_session_sees_memory_without_resume(
    world: MemoryWorld, tmp_path: Path
) -> None:
    lead = await world.agent("lead")
    tree = tmp_path / "tree"
    tree.mkdir()

    await world.run(lead, task_id=world.task_ids[0], cwd=tree, writes=NOTE)
    await world.run(lead, task_id=world.task_ids[1], cwd=tree)

    request = world.fake.requests[-1]
    assert request.resume_session_id is None
    assert NOTE in request.prompt


async def test_resume_still_continues_the_tasks_session_with_memory(
    world: MemoryWorld, tmp_path: Path
) -> None:
    lead = await world.agent("lead")
    tree = tmp_path / "tree"
    tree.mkdir()

    await world.run(lead, task_id=world.task_ids[0], cwd=tree, writes=NOTE)
    await world.run(lead, task_id=world.task_ids[0])

    request = world.fake.requests[-1]
    assert request.resume_session_id == world.fake.session_id
    assert request.cwd == tree
    assert NOTE in request.prompt


async def test_a_memory_change_in_an_interrupted_run_is_kept(world: MemoryWorld) -> None:
    manager = await world.agent("manager")
    world.fake.wait_for_interrupt = True

    active = await world.start(manager)
    write_memory(world.last_cwd(), NOTE)
    await active.interrupt()
    run = await active.wait()

    assert run.status is RunStatus.INTERRUPTED
    assert MEMORY_EVENT in await event_kinds(world, run.id)
    world.fake.wait_for_interrupt = False
    await world.run(manager)
    assert NOTE in world.last_prompt()


async def test_a_memory_change_in_a_failed_run_is_kept(world: MemoryWorld) -> None:
    manager = await world.agent("manager")
    world.fake.fail_with = AdapterError("stream broke")

    run = (await world.run(manager, writes=NOTE)).run

    assert run.status is RunStatus.FAILED
    assert world.memory.read(manager) == NOTE


async def test_an_unchanged_memory_records_no_event(world: MemoryWorld) -> None:
    manager = await world.agent("manager")
    await world.run(manager, writes=NOTE)

    second = await world.run(manager)

    assert MEMORY_EVENT not in await event_kinds(world, second.run_id)


async def test_a_workers_prompt_has_no_memory_section(world: MemoryWorld) -> None:
    worker = await world.agent("worker")

    await world.run(worker)

    request = world.fake.requests[-1]
    assert MEMORY_HEADING not in request.prompt
    assert request.prompt == "Do the work."
    assert request.cwd is None
    assert not world.memory.home(worker).exists()


async def test_agent_config_overrides_the_role_default(world: MemoryWorld) -> None:
    remembering_worker = await world.agent("worker", {MEMORY_CONFIG_KEY: True})
    forgetful_manager = await world.agent("manager", {MEMORY_CONFIG_KEY: False})

    await world.run(remembering_worker)
    assert MEMORY_HEADING in world.last_prompt()
    await world.run(forgetful_manager)
    assert MEMORY_HEADING not in world.last_prompt()
