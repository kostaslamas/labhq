"""Rows the Call Center tests share: an open call, an owner request, a pending question and
the global CEO."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.questions import raise_question
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Call, CallRequest
from tests.db.factories import project_agent_task


@dataclass(frozen=True)
class Scene:
    agent_id: int
    task_id: int
    call_id: int
    question_id: int


async def open_call(session: AsyncSession, clock: Clock, agent_id: int | None = None) -> Call:
    now = clock.now()
    call = Call(agent_id=agent_id, opened_at=now, last_activity_at=now)
    session.add(call)
    await session.flush()
    return call


async def owner_request(
    session: AsyncSession, clock: Clock, call_id: int, request_id: str, text: str
) -> CallRequest:
    request = CallRequest(call_id=call_id, request_id=request_id, text=text, created_at=clock.now())
    session.add(request)
    await session.flush()
    return request


async def scene(session: AsyncSession, clock: Clock, question: str = "Which branch?") -> Scene:
    _, agent, task = await project_agent_task(session, clock)
    asked = await raise_question(session, clock, agent_id=agent.id, task_id=task.id, text=question)
    assert asked is not None
    call = await open_call(session, clock)
    scene_ids = Scene(agent.id, task.id, call.id, asked.id)
    await session.commit()
    return scene_ids


async def add_ceo(session: AsyncSession, clock: Clock) -> Agent:
    now = clock.now()
    ceo = Agent(
        project_id=None,
        role="ceo",
        title="CEO",
        adapter="fake",
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(ceo)
    await session.flush()
    return ceo
