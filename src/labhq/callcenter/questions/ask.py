"""Turn a question an agent wrote into one row and one outbox notification, once.

The fingerprint covers agent, task and text, so reading the same status file twice (or
from two processes) inserts nothing new. The notification is written in the caller's
transaction with the question, so a question can never exist without its alert: the
notifier (`labhq.notify`) sends every pending row and this module never imports it.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.questions.reference import format_reference
from labhq.clock import Clock
from labhq.db.enums import NotificationStatus, QuestionStatus
from labhq.db.models import Agent, AgentQuestion, Notification

NOTIFICATION_KIND = "agent_question"
TITLE_MAX_CHARS = 200


def question_fingerprint(agent_id: int, task_id: int | None, text: str) -> str:
    key = f"{agent_id}\x1f{task_id if task_id is not None else ''}\x1f{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def idempotency_key(question_id: int) -> str:
    return f"{NOTIFICATION_KIND}:{question_id}"


async def raise_question(
    db: AsyncSession, clock: Clock, *, agent_id: int, task_id: int | None, text: str
) -> AgentQuestion | None:
    """Store a new question and its notification; return None when it was already known.

    Flushes but never commits: the caller owns the transaction.
    """
    now = clock.now()
    inserted = await db.execute(
        insert(AgentQuestion)
        .values(
            agent_id=agent_id,
            task_id=task_id,
            question=text,
            fingerprint=question_fingerprint(agent_id, task_id, text),
            status=QuestionStatus.PENDING,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["fingerprint"])
        .returning(AgentQuestion.id)
    )
    question_id = inserted.scalar_one_or_none()
    if question_id is None:
        return None
    agent = await db.get_one(Agent, agent_id)
    reference = format_reference(question_id)
    await db.execute(
        insert(Notification)
        .values(
            kind=NOTIFICATION_KIND,
            subject=f"question:{question_id}",
            title=f"{reference}: question from {agent.title}"[:TITLE_MAX_CHARS],
            body=f"{text}\n\nReference: {reference}",
            status=NotificationStatus.PENDING,
            attempts=0,
            idempotency_key=idempotency_key(question_id),
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return await db.scalar(
        select(AgentQuestion)
        .where(AgentQuestion.id == question_id)
        .execution_options(populate_existing=True)
    )
