from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.deliveries import deliver
from labhq.clock import FakeClock
from labhq.db.enums import WakeupSource
from labhq.db.models import Delivery, WakeupRequest
from labhq.scheduler import Outcome
from tests.callcenter.factories import owner_request, scene


async def test_a_second_delivery_coalesces_but_the_words_reach_the_brief(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", "First words")
    await owner_request(session, clock, s.call_id, "req-2", "Second words")
    kwargs = {"call_id": s.call_id, "agent_id": s.agent_id, "task_id": s.task_id}

    first = await deliver(
        session, clock, request_id="req-1", text="First words", label="A", **kwargs
    )
    second = await deliver(
        session, clock, request_id="req-2", text="Second words", label="B", **kwargs
    )
    await session.commit()

    assert (first.outcome, second.outcome) == (Outcome.CREATED, Outcome.COALESCED)
    pending = [r for r in await session.scalars(select(WakeupRequest)) if r.coalesced_count]
    [carrier] = pending
    assert "First words" in carrier.reason
    assert "Second words" in carrier.reason
    assert len((await session.scalars(select(Delivery))).all()) == 2


async def test_a_delivery_is_idempotent_per_request_label_and_agent(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", "Words")
    kwargs = {
        "call_id": s.call_id,
        "request_id": "req-1",
        "agent_id": s.agent_id,
        "task_id": s.task_id,
        "text": "Words",
        "label": "L",
    }
    await deliver(session, clock, **kwargs)
    again = await deliver(session, clock, **kwargs)
    await session.commit()
    assert again.outcome is Outcome.DUPLICATE
    assert len((await session.scalars(select(WakeupRequest))).all()) == 1


async def test_a_task_less_question_wakes_the_agent_without_a_task(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", "Words")
    await deliver(
        session,
        clock,
        call_id=s.call_id,
        request_id="req-1",
        agent_id=s.agent_id,
        task_id=None,
        text="Words",
        label="L",
    )
    wakeup = (await session.scalars(select(WakeupRequest))).one()
    assert (wakeup.task_id, wakeup.source) == (None, WakeupSource.MEETING)
