import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.actions import order
from labhq.clock import FakeClock
from labhq.db.enums import WakeupSource
from labhq.db.models import Task, WakeupRequest
from labhq.speech import speakable
from tests.db.factories import project_agent_task


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_order_creates_one_task_and_one_assignment_wakeup(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, _ = await project_agent_task(session, clock)
    await session.commit()
    tasks_before = await _count(session, Task)

    answer = await order(
        session, clock, project="demo", text="Fix the login bug", request_id="r1", assignee=agent.id
    )

    assert await _count(session, Task) == tasks_before + 1
    task = await session.scalar(select(Task).where(Task.title == "Fix the login bug"))
    assert task is not None
    assert task.assignee_id == agent.id
    wakeups = list(await session.scalars(select(WakeupRequest)))
    assert [(w.source, w.task_id) for w in wakeups] == [(WakeupSource.ASSIGNMENT, task.id)]
    assert f"T{task.id}" in answer
    assert speakable(answer) == answer


async def test_a_repeat_with_the_same_request_id_creates_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, _ = await project_agent_task(session, clock)
    await session.commit()

    first = await order(
        session, clock, project="demo", text="Fix it", request_id="r1", assignee=agent.id
    )
    tasks, wakeups = await _count(session, Task), await _count(session, WakeupRequest)
    second = await order(
        session, clock, project="demo", text="Fix it", request_id="r1", assignee=agent.id
    )

    assert second == first
    assert (await _count(session, Task), await _count(session, WakeupRequest)) == (tasks, wakeups)


async def test_a_new_request_id_creates_a_new_task(session: AsyncSession, clock: FakeClock) -> None:
    await project_agent_task(session, clock)
    await session.commit()
    before = await _count(session, Task)

    await order(session, clock, project="demo", text="Same words", request_id="r1")
    await order(session, clock, project="demo", text="Same words", request_id="r2")

    assert await _count(session, Task) == before + 2
    assert await _count(session, WakeupRequest) == 0  # unassigned: nobody to wake


async def test_an_unknown_project_is_explained_and_creates_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    before = await _count(session, Task)

    answer = await order(session, clock, project="ghost", text="Do it", request_id="r1")

    assert "no project" in answer
    assert await _count(session, Task) == before
    assert speakable(answer) == answer


async def test_an_unknown_assignee_is_explained(session: AsyncSession, clock: FakeClock) -> None:
    await project_agent_task(session, clock)
    await session.commit()
    before = await _count(session, Task)

    answer = await order(
        session, clock, project="demo", text="Do it", request_id="r1", assignee=999
    )

    assert "no agent 999" in answer
    assert await _count(session, Task) == before
    assert speakable(answer) == answer


async def test_a_malformed_request_id_is_rejected(session: AsyncSession, clock: FakeClock) -> None:
    with pytest.raises(ValueError, match="request_id"):
        await order(session, clock, project="demo", text="x", request_id="a\nb")
