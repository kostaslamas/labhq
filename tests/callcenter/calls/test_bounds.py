"""deliver and interrupt carry only the owner's stored words, to a recipient the owner chose."""

from dataclasses import dataclass

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.calls import BoundError, deliver_request, interrupt_request
from labhq.clock import FakeClock
from labhq.db.models import Agent, Delivery, WakeupRequest
from tests.callcenter.factories import open_call, owner_request, scene
from tests.db.factories import project_agent_task


class RecordingInterrupter:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.calls: list[int] = []

    async def interrupt(self, agent_id: int) -> bool:
        self.calls.append(agent_id)
        return self.running


@dataclass(frozen=True)
class Office:
    """Plain ids, so nothing expires under the test after a commit."""

    worker: int
    bystander: int
    call: int
    other_call: int


@pytest.fixture
async def office(session: AsyncSession, clock: FakeClock) -> Office:
    project, worker, _ = await project_agent_task(session, clock)
    now = clock.now()
    bystander = Agent(
        project_id=project.id,
        role="worker",
        title="Reviewer",
        adapter="fake",
        created_at=now,
        updated_at=now,
    )
    session.add(bystander)
    await session.flush()
    call, other = await open_call(session, clock), await open_call(session, clock)
    ids = Office(worker.id, bystander.id, call.id, other.id)
    await session.commit()
    return ids


async def _ask(session: AsyncSession, clock: FakeClock, call_id: int, text: str) -> None:
    await owner_request(session, clock, call_id, "r1", text)
    await session.commit()


async def _deliveries(session: AsyncSession) -> list[Delivery]:
    session.expire_all()
    return list((await session.scalars(select(Delivery))).all())


async def test_a_request_the_owner_named_an_agent_in_is_delivered_verbatim(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    words = "Tell the worker to use main."
    await _ask(session, clock, office.call, words)

    said = await deliver_request(
        session, clock, call_id=office.call, request_id="r1", agent_id=office.worker
    )

    [delivery] = await _deliveries(session)
    assert (delivery.call_id, delivery.request_id) == (office.call, "r1")
    assert (delivery.recipient_agent_id, delivery.text) == (office.worker, words)
    assert delivery.interrupted is False
    wakeup = await session.scalar(select(WakeupRequest))
    assert wakeup is not None and wakeup.reason.endswith(words)
    assert "Worker" in said


async def test_deliver_refuses_a_request_id_from_another_call(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.other_call, "Tell the worker to stop.")

    with pytest.raises(BoundError, match="not part of this call"):
        await deliver_request(
            session, clock, call_id=office.call, request_id="r1", agent_id=office.worker
        )
    assert await _deliveries(session) == []


async def test_deliver_refuses_a_recipient_neither_named_nor_asking(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.call, "Tell the worker to use main.")

    with pytest.raises(BoundError, match="did not name Reviewer"):
        await deliver_request(
            session, clock, call_id=office.call, request_id="r1", agent_id=office.bystander
        )
    assert await _deliveries(session) == []
    assert await session.scalar(select(func.count()).select_from(WakeupRequest)) == 0


async def test_an_agent_named_by_its_id_may_receive(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.call, f"Tell agent {office.bystander} to look at it.")

    await deliver_request(
        session, clock, call_id=office.call, request_id="r1", agent_id=office.bystander
    )

    assert [d.recipient_agent_id for d in await _deliveries(session)] == [office.bystander]


async def test_an_agent_with_a_pending_question_may_receive_unnamed(
    session: AsyncSession, clock: FakeClock
) -> None:
    s = await scene(session, clock)
    await _ask(session, clock, s.call_id, "Use main.")

    await deliver_request(session, clock, call_id=s.call_id, request_id="r1", agent_id=s.agent_id)

    assert [d.recipient_agent_id for d in await _deliveries(session)] == [s.agent_id]


async def test_a_request_is_delivered_once_per_recipient(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.call, "Worker, use main.")

    for _ in range(2):
        await deliver_request(
            session, clock, call_id=office.call, request_id="r1", agent_id=office.worker
        )

    assert len(await _deliveries(session)) == 1


async def test_interrupt_without_the_owners_request_is_refused(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    # The words name the worker, so only the missing interrupt request refuses it.
    await _ask(session, clock, office.call, "Tell the worker to use main.")
    interrupter = RecordingInterrupter()

    with pytest.raises(BoundError, match="did not ask for an interrupt"):
        await interrupt_request(
            session,
            clock,
            interrupter,
            call_id=office.call,
            request_id="r1",
            agent_id=office.worker,
        )
    assert interrupter.calls == []
    assert await _deliveries(session) == []


async def test_interrupt_asked_in_another_call_is_refused(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.other_call, "Interrupt the worker now.")
    interrupter = RecordingInterrupter()

    with pytest.raises(BoundError, match="not part of this call"):
        await interrupt_request(
            session,
            clock,
            interrupter,
            call_id=office.call,
            request_id="r1",
            agent_id=office.worker,
        )
    assert interrupter.calls == []


async def test_interrupt_the_owner_asked_for_stops_the_turn_once_and_is_recorded(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    words = "Interrupt the worker and tell it to stop pushing."
    await _ask(session, clock, office.call, words)
    interrupter = RecordingInterrupter()

    said = await interrupt_request(
        session, clock, interrupter, call_id=office.call, request_id="r1", agent_id=office.worker
    )
    with pytest.raises(BoundError, match="already interrupted"):
        await interrupt_request(
            session,
            clock,
            interrupter,
            call_id=office.call,
            request_id="r1",
            agent_id=office.worker,
        )

    assert interrupter.calls == [office.worker]
    [delivery] = await _deliveries(session)
    assert (delivery.text, delivery.interrupted) == (words, True)
    assert "Interrupted" in said


async def test_an_interrupt_nobody_can_reach_still_delivers_and_says_so(
    session: AsyncSession, clock: FakeClock, office: Office
) -> None:
    await _ask(session, clock, office.call, "Interrupt the worker, it should stop.")

    said = await interrupt_request(
        session,
        clock,
        RecordingInterrupter(running=False),
        call_id=office.call,
        request_id="r1",
        agent_id=office.worker,
    )

    [delivery] = await _deliveries(session)
    assert delivery.interrupted is False
    assert "when its turn ends" in said
