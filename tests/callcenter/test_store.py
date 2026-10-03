import asyncio
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from labhq.callcenter.store import answer_question_once
from labhq.clock import FakeClock
from labhq.db.enums import QuestionStatus
from labhq.db.models import AgentQuestion
from tests.db.factories import project_agent_task


async def _pending_question(session: AsyncSession, clock: FakeClock) -> int:
    _, agent, task = await project_agent_task(session, clock)
    question = AgentQuestion(
        agent_id=agent.id,
        task_id=task.id,
        question="Which branch?",
        fingerprint="a" * 64,
        created_at=clock.now(),
    )
    session.add(question)
    await session.commit()
    return question.id


async def test_first_answer_wins_and_is_recorded(session: AsyncSession, clock: FakeClock) -> None:
    question_id = await _pending_question(session, clock)
    won = await answer_question_once(session, question_id, "main", "req-1", clock.now())
    await session.commit()
    row = (await session.execute(select(AgentQuestion))).scalar_one()
    assert won is True
    assert (row.status, row.answer, row.answer_request_id) == (
        QuestionStatus.ANSWERED,
        "main",
        "req-1",
    )
    assert row.answered_at == clock.now()


async def test_second_answer_loses_and_changes_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    question_id = await _pending_question(session, clock)
    await answer_question_once(session, question_id, "main", "req-1", clock.now())
    won = await answer_question_once(session, question_id, "develop", "req-2", clock.now())
    await session.commit()
    row = (await session.execute(select(AgentQuestion))).scalar_one()
    assert won is False
    assert (row.answer, row.answer_request_id) == ("main", "req-1")


async def test_unknown_question_is_not_won(session: AsyncSession, clock: FakeClock) -> None:
    assert await answer_question_once(session, 999, "x", "req-1", clock.now()) is False


async def test_concurrent_answers_have_exactly_one_winner(
    session: AsyncSession, database_url: str, clock: FakeClock
) -> None:
    question_id = await _pending_question(session, clock)
    engine = create_async_engine(database_url)
    factory: Callable[[], AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt(request_id: str, now: datetime) -> bool:
        async with factory() as other:
            won = await answer_question_once(other, question_id, request_id, request_id, now)
            await other.commit()
            return won

    try:
        results = await asyncio.gather(attempt("req-a", clock.now()), attempt("req-b", clock.now()))
    finally:
        await engine.dispose()
    assert sorted(results) == [False, True]
