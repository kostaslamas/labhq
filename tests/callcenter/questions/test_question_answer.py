import asyncio
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from labhq.callcenter.questions import AnswerError, InvalidReferenceError, answer
from labhq.clock import FakeClock
from labhq.db.enums import QuestionStatus, WakeupStatus
from labhq.db.models import AgentQuestion, Delivery, WakeupRequest
from labhq.speech import speakable
from tests.callcenter.factories import owner_request, scene

WORDS = "Use main, and don't touch the release branch."


async def test_the_owners_stored_words_are_delivered_verbatim_and_recorded(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", WORDS)
    await session.commit()

    spoken = await answer(
        session, clock, f"Q{s.question_id}", call_id=s.call_id, request_id="req-1"
    )

    [delivery] = (await session.scalars(select(Delivery))).all()
    assert (delivery.call_id, delivery.request_id) == (s.call_id, "req-1")
    assert delivery.recipient_agent_id == s.agent_id
    assert delivery.text == WORDS
    assert delivery.interrupted is False
    [wakeup] = (await session.scalars(select(WakeupRequest))).all()
    assert (wakeup.agent_id, wakeup.task_id) == (s.agent_id, s.task_id)
    assert wakeup.status is WakeupStatus.PENDING
    assert wakeup.reason.endswith(WORDS)
    assert speakable(spoken) == spoken
    assert f"Q{s.question_id}" in spoken


async def test_a_second_answer_is_refused_and_delivers_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", WORDS)
    await owner_request(session, clock, s.call_id, "req-2", "Actually develop.")
    await session.commit()
    reference = f"Q{s.question_id}"
    await answer(session, clock, reference, call_id=s.call_id, request_id="req-1")

    spoken = await answer(session, clock, reference, call_id=s.call_id, request_id="req-2")

    assert "already answered" in spoken
    question = (await session.scalars(select(AgentQuestion))).one()
    assert (question.status, question.answer, question.answer_request_id) == (
        QuestionStatus.ANSWERED,
        WORDS,
        "req-1",
    )
    assert len((await session.scalars(select(Delivery))).all()) == 1


async def test_two_concurrent_answers_store_and_deliver_exactly_one(
    session: AsyncSession, database_url: str, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-a", "Words A")
    await owner_request(session, clock, s.call_id, "req-b", "Words B")
    await session.commit()
    engine = create_async_engine(database_url)
    factory: Callable[[], AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt(request_id: str) -> str:
        async with factory() as other:
            return await answer(
                other, clock, f"Q{s.question_id}", call_id=s.call_id, request_id=request_id
            )

    try:
        spoken = await asyncio.gather(attempt("req-a"), attempt("req-b"))
    finally:
        await engine.dispose()

    assert sum("already answered" in line for line in spoken) == 1
    session.expire_all()
    [delivery] = (await session.scalars(select(Delivery))).all()
    question = (await session.scalars(select(AgentQuestion))).one()
    assert delivery.recipient_agent_id == s.agent_id
    assert (question.answer, question.answer_request_id) == (delivery.text, delivery.request_id)
    assert len((await session.scalars(select(WakeupRequest))).all()) == 1


async def test_a_request_from_another_call_is_refused(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", WORDS)
    await session.commit()
    with pytest.raises(AnswerError):
        await answer(session, clock, f"Q{s.question_id}", call_id=s.call_id + 1, request_id="req-1")
    question = (await session.scalars(select(AgentQuestion))).one()
    assert question.status is QuestionStatus.PENDING


async def test_unknown_questions_and_bad_references_are_refused(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", WORDS)
    await session.commit()
    with pytest.raises(AnswerError):
        await answer(session, clock, "Q999", call_id=s.call_id, request_id="req-1")
    with pytest.raises(InvalidReferenceError):
        await answer(session, clock, "the branch one", call_id=s.call_id, request_id="req-1")
