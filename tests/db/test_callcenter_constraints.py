"""Uniqueness the Call Center tables enforce regardless of the code that writes them."""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import AgentQuestion, Call, CallRequest, Notification
from tests.db.factories import project_agent_task


def _call(now: datetime) -> Call:
    return Call(opened_at=now, last_activity_at=now)


async def test_duplicate_request_id_is_rejected(session: AsyncSession, clock: FakeClock) -> None:
    now = clock.now()
    call = _call(now)
    session.add(call)
    await session.flush()
    for _ in range(2):
        session.add(CallRequest(call_id=call.id, request_id="req-1", text="hello", created_at=now))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.flush()


async def test_duplicate_notification_idempotency_key_is_rejected(
    session: AsyncSession, clock: FakeClock
) -> None:
    for _ in range(2):
        session.add(
            Notification(
                kind="test",
                subject="test:1",
                title="t",
                body="b",
                idempotency_key="test:1",
                created_at=clock.now(),
            )
        )
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.flush()


async def test_duplicate_question_fingerprint_is_rejected(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, task = await project_agent_task(session, clock)
    for _ in range(2):
        session.add(
            AgentQuestion(
                agent_id=agent.id,
                task_id=task.id,
                question="Which branch?",
                fingerprint="f" * 64,
                created_at=clock.now(),
            )
        )
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.flush()
