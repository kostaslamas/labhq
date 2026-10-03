"""Answer an agent's question with the owner's words, at most once.

The words come from the stored `call_requests` row, never from the caller's arguments, so
nothing a model composed can reach the agent (ADR 0004). The answer goes to the asker
recorded on the question row. Which of two racing answers counts is decided by one
conditional UPDATE (`answer_question_once`); the loser stores and delivers nothing.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.deliveries import deliver
from labhq.callcenter.questions.reference import format_reference, parse_reference
from labhq.callcenter.store import answer_question_once
from labhq.clock import Clock
from labhq.db.models import Agent, AgentQuestion, CallRequest
from labhq.speech import speakable


class AnswerError(LookupError):
    """The reference or request names nothing the caller may use."""


async def answer(
    db: AsyncSession, clock: Clock, reference: str, *, call_id: int, request_id: str
) -> str:
    """Answer the question named by `reference` with the words of request `request_id`.

    Returns a spoken confirmation. Commits: the stored answer, the wakeup and the delivery
    row are one unit, and the winner commits before the loser's update can run.
    """
    question_id = parse_reference(reference)
    spoken = format_reference(question_id)
    # The request must belong to this call: a request id from another call is refused.
    request = await db.scalar(
        select(CallRequest).where(
            CallRequest.request_id == request_id, CallRequest.call_id == call_id
        )
    )
    if request is None:
        raise AnswerError(f"no request {request_id!r} in call {call_id}")
    question = await db.get(AgentQuestion, question_id)
    if question is None:
        raise AnswerError(f"no question {spoken}")

    won = await answer_question_once(db, question_id, request.text, request_id, clock.now())
    if not won:
        await db.rollback()
        return speakable(f"{spoken} was already answered.")

    agent = await db.get_one(Agent, question.agent_id)
    result = await deliver(
        db,
        clock,
        call_id=call_id,
        request_id=request_id,
        agent_id=question.agent_id,
        task_id=question.task_id,
        text=request.text,
        label=f"Answer to {spoken}",
    )
    await db.commit()
    if result.delivery is None:
        return speakable(f"Stored your answer to {spoken}, but {agent.title} cannot wake yet.")
    return speakable(f"Sent your answer to {spoken} to {agent.title}.")
