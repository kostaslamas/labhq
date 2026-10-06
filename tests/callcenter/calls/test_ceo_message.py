"""The Call Center sends the CEO the owner's words, or a wording the owner confirmed, and nothing
else; an unconfirmed or rejected proposal sends nothing."""

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.calls import BoundError, confirm_wording, propose_wording, send_request
from labhq.ceochat import message_text
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, ProposalStatus, WakeupSource
from labhq.db.models import Agent, Task, WakeupRequest, WordingProposal
from tests.callcenter.factories import add_ceo, open_call, owner_request
from tests.db.factories import project_agent_task

SPOKEN = "uh tell the team to to ship the login form  by friday"
CLEARER = "Ship the login form by Friday."


@dataclass(frozen=True)
class Line:
    ceo: int
    call: int
    other_call: int


@pytest.fixture
async def line(session: AsyncSession, clock: FakeClock) -> Line:
    await project_agent_task(session, clock)
    ceo = await add_ceo(session, clock)
    call, other = await open_call(session, clock), await open_call(session, clock)
    await owner_request(session, clock, call.id, "r1", SPOKEN)
    await owner_request(session, clock, other.id, "elsewhere", "Something else.")
    ids = Line(ceo.id, call.id, other.id)
    await session.commit()
    return ids


async def sent(session: AsyncSession) -> list[WakeupRequest]:
    session.expire_all()
    return list(await session.scalars(select(WakeupRequest).order_by(WakeupRequest.id)))


async def texts(session: AsyncSession) -> list[str]:
    return [message_text(request.reason) for request in await sent(session)]


async def say(
    session: AsyncSession, clock: FakeClock, call: int, request_id: str, text: str
) -> None:
    await owner_request(session, clock, call, request_id, text)
    await session.commit()


async def test_an_order_reaches_the_ceo_as_the_owners_exact_words_and_creates_no_task(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    tasks = await session.scalar(select(func.count()).select_from(Task))

    said = await send_request(session, clock, call_id=line.call, request_id="r1")

    (message,) = await sent(session)
    assert said == "Sent to the CEO."
    assert (message.agent_id, message.source, message.task_id) == (
        line.ceo,
        WakeupSource.OWNER_MESSAGE,
        None,
    )
    assert message_text(message.reason) == SPOKEN
    # The stored reason is the words and the CEO conversation, nothing the Call Center added.
    assert json.loads(message.reason) == {"text": SPOKEN, "history": []}
    assert await session.scalar(select(func.count()).select_from(Task)) == tasks


async def test_a_retry_with_the_same_request_sends_nothing_twice(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    await send_request(session, clock, call_id=line.call, request_id="r1")
    again = await send_request(session, clock, call_id=line.call, request_id="r1")

    assert again == "That was already sent to the CEO."
    assert await texts(session) == [SPOKEN]


async def test_a_request_of_another_call_is_refused(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    with pytest.raises(BoundError, match="not part of this call"):
        await send_request(session, clock, call_id=line.call, request_id="elsewhere")
    assert await sent(session) == []


async def test_a_confirmed_proposal_is_sent_exactly_as_read_back(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    stored = await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    assert await sent(session) == []
    assert f'"{CLEARER}"' in stored
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id
    await say(session, clock, line.call, "r2", "Yes, send it.")

    said = await confirm_wording(
        session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r2"
    )

    assert said == "Sent to the CEO."
    assert await texts(session) == [CLEARER]
    await session.refresh(proposal)
    assert (proposal.status, proposal.decided_by_request_id) == (ProposalStatus.SENT, "r2")
    # The owner's original words stay stored next to it, unchanged.
    assert proposal.request_id == "r1"


async def test_an_unconfirmed_proposal_is_never_sent(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id
    await say(session, clock, line.call, "r2", "Hmm, what about the docs?")

    # The request the proposal was made from cannot confirm it, nor can an unclear answer.
    for request_id in ("r1", "r2"):
        with pytest.raises(BoundError):
            await confirm_wording(
                session, clock, call_id=line.call, proposal_id=proposal_id, request_id=request_id
            )
        await session.rollback()

    assert await sent(session) == []
    await session.refresh(proposal)
    assert proposal.status is ProposalStatus.PENDING


async def test_a_request_stored_before_the_proposal_cannot_confirm_it(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    # The owner said yes to something else before hearing the proposal.
    await say(session, clock, line.call, "r2", "Yes.")
    await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id

    with pytest.raises(BoundError, match="before the owner heard"):
        await confirm_wording(
            session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r2"
        )
    await session.rollback()
    assert await sent(session) == []


async def test_a_rejected_proposal_sends_nothing_and_cannot_be_sent_later(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id
    await say(session, clock, line.call, "r2", "No, that's not right.")
    await say(session, clock, line.call, "r3", "Yes.")

    said = await confirm_wording(
        session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r2"
    )
    with pytest.raises(BoundError, match="already rejected"):
        await confirm_wording(
            session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r3"
        )
    await session.rollback()

    assert said == f"Proposal {proposal_id} is rejected. Nothing was sent."
    assert await sent(session) == []


async def test_the_owners_words_and_a_confirmed_wording_are_never_both_sent(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id
    await say(session, clock, line.call, "r2", "Yes.")
    await confirm_wording(
        session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r2"
    )

    with pytest.raises(BoundError, match="confirmed wording"):
        await send_request(session, clock, call_id=line.call, request_id="r1")
    await session.rollback()
    with pytest.raises(BoundError, match="already sent"):
        await propose_wording(session, clock, call_id=line.call, request_id="r1", text="Again.")
    await session.rollback()

    assert await texts(session) == [CLEARER]


async def test_without_a_ceo_nothing_is_sent_and_the_proposal_stays_unsent(
    session: AsyncSession, clock: FakeClock, line: Line
) -> None:
    ceo = await session.get_one(Agent, line.ceo)
    ceo.status = AgentStatus.RETIRED
    await session.commit()
    await propose_wording(session, clock, call_id=line.call, request_id="r1", text=CLEARER)
    (proposal,) = list(await session.scalars(select(WordingProposal)))
    proposal_id = proposal.id
    await say(session, clock, line.call, "r2", "Yes.")

    said = await confirm_wording(
        session, clock, call_id=line.call, proposal_id=proposal_id, request_id="r2"
    )

    assert said.startswith("Nothing was sent.")
    assert await sent(session) == []
    await session.refresh(proposal)
    assert proposal.status is ProposalStatus.PENDING
