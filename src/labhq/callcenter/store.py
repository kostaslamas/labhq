"""Small database primitives the Call Center builds on."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import QuestionStatus
from labhq.db.models import AgentQuestion


async def answer_question_once(
    db: AsyncSession,
    question_id: int,
    answer: str,
    request_id: str,
    now: datetime,
) -> bool:
    """Record the answer if the question is still pending; return whether this call won.

    One conditional UPDATE, not read-then-write: a voice answer and a program answer can race,
    and the database, not the caller, decides which one counts. The caller commits.
    """
    result = await db.execute(
        update(AgentQuestion)
        .where(
            AgentQuestion.id == question_id,
            AgentQuestion.status == QuestionStatus.PENDING,
        )
        .values(
            status=QuestionStatus.ANSWERED,
            answer=answer,
            answer_request_id=request_id,
            answered_at=now,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
