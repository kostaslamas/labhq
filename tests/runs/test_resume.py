"""A second run of the same agent on the same task resumes the stored session."""

import dataclasses
from pathlib import Path

from labhq.adapters import AdapterResult, FakeAdapter
from labhq.db.models import Task
from tests.runs.conftest import World
from tests.runs.helpers import stored_run, task_sessions, use_adapter


async def test_second_run_resumes_the_first_runs_session(world: World, tmp_path: Path) -> None:
    first = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt="start", cwd=tmp_path
    )
    second = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt="continue"
    )

    assert (await stored_run(world, first.id)).session_id_before is None
    resumed = await stored_run(world, second.id)
    assert resumed.session_id_before == "fake-session-1"
    assert resumed.session_id_after == "fake-session-1"
    assert [request.resume_session_id for request in world.fake.requests] == [
        None,
        "fake-session-1",
    ]
    # Sessions live per working directory, so the resumed run reuses the stored one.
    assert world.fake.requests[1].cwd == tmp_path
    (row,) = await task_sessions(world)
    assert (row.session_id, row.adapter, row.cwd) == ("fake-session-1", "fake", str(tmp_path))


async def test_claude_resume_reaches_the_sdk_options(world: World, tmp_path: Path) -> None:
    await use_adapter(world, "claude")
    for prompt in ("Remember AURORA-7.", "What was the codeword?"):
        await world.service.execute(
            agent_id=world.agent_id, task_id=world.task_id, prompt=prompt, cwd=tmp_path
        )
    assert [options.resume for options in world.claude.options] == [None, "stub-session-1"]
    assert {options.cwd for options in world.claude.options} == {tmp_path}


class _Forks(FakeAdapter):
    """Reports a new session id even when asked to resume, as a forked session would."""

    def _final_result(self) -> AdapterResult:
        return dataclasses.replace(super()._final_result(), session_id="fake-session-2")


async def test_a_new_session_id_replaces_the_stored_one(world: World) -> None:
    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="a")
    world.registry.register("fake", lambda: _Forks(world.fake), replace=True)
    second = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="b")
    stored = await stored_run(world, second.id)
    assert (stored.session_id_before, stored.session_id_after) == (
        "fake-session-1",
        "fake-session-2",
    )
    (row,) = await task_sessions(world)
    assert row.session_id == "fake-session-2"


async def test_another_task_starts_a_fresh_session(world: World) -> None:
    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="a")
    async with world.sessions() as db:
        other = Task(
            project_id=world.project_id,
            title="Other task",
            created_at=world.clock.now(),
            updated_at=world.clock.now(),
        )
        db.add(other)
        await db.commit()
    run = await world.service.execute(agent_id=world.agent_id, task_id=other.id, prompt="b")
    assert (await stored_run(world, run.id)).session_id_before is None


async def test_a_session_from_another_adapter_is_not_resumed(world: World) -> None:
    await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="a")
    await use_adapter(world, "claude")
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="b")
    assert (await stored_run(world, run.id)).session_id_before is None
    assert world.claude.options[0].resume is None


async def test_a_run_without_a_task_stores_no_session(world: World) -> None:
    await world.service.execute(agent_id=world.agent_id, task_id=None, prompt="a")
    assert await task_sessions(world) == []


async def test_a_session_kept_outside_tasks_is_resumed_when_given(world: World) -> None:
    # A Call Center call keeps its session on its own row and runs without a task.
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=None, prompt="again", resume_session_id="call-session"
    )

    assert world.fake.requests[0].resume_session_id == "call-session"
    assert (await stored_run(world, run.id)).session_id_before == "call-session"
    assert await task_sessions(world) == []
