"""A voice order goes to the CEO in the owner's exact words; it creates no task by itself."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.actions import order
from labhq.ceochat import message_text
from labhq.clock import FakeClock
from labhq.db.enums import CallRequestStatus, WakeupSource
from labhq.db.models import CallRequest, Task, WakeupRequest
from labhq.speech import speakable
from tests.callcenter.factories import add_ceo
from tests.db.factories import project_agent_task

# Spoken words keep their stray spaces and casing: nothing tidies them on the way.
WORDS = "Have the demo team fix the login bug  before   the release"


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _messages(session: AsyncSession) -> list[WakeupRequest]:
    session.expire_all()
    return list(await session.scalars(select(WakeupRequest).order_by(WakeupRequest.id)))


@pytest.fixture
async def ceo_id(session: AsyncSession, clock: FakeClock) -> int:
    await project_agent_task(session, clock)
    ceo = await add_ceo(session, clock)
    await session.commit()
    return ceo.id


async def test_an_order_reaches_the_ceo_verbatim_and_creates_no_task(
    session: AsyncSession, clock: FakeClock, ceo_id: int
) -> None:
    tasks = await _count(session, Task)

    answer = await order(session, clock, text=WORDS, request_id="r1")

    (message,) = await _messages(session)
    assert (message.agent_id, message.source) == (ceo_id, WakeupSource.OWNER_MESSAGE)
    assert message_text(message.reason) == WORDS
    assert await _count(session, Task) == tasks
    assert answer == "Sent to the CEO."
    assert speakable(answer) == answer


async def test_the_order_is_stored_as_a_request_the_call_center_agent_never_takes(
    session: AsyncSession, clock: FakeClock, ceo_id: int
) -> None:
    await order(session, clock, text=WORDS, request_id="r1")

    (request,) = list(await session.scalars(select(CallRequest)))
    assert (request.request_id, request.text) == ("order-r1", WORDS)
    assert request.status is CallRequestStatus.ANSWERED


async def test_a_repeat_with_the_same_request_id_sends_nothing_twice(
    session: AsyncSession, clock: FakeClock, ceo_id: int
) -> None:
    await order(session, clock, text=WORDS, request_id="r1")
    again = await order(session, clock, text=WORDS, request_id="r1")

    assert again == "That was already sent to the CEO."
    assert len(await _messages(session)) == 1
    assert await _count(session, CallRequest) == 1


async def test_a_new_request_id_is_a_new_message(
    session: AsyncSession, clock: FakeClock, ceo_id: int
) -> None:
    await order(session, clock, text="Same words", request_id="r1")
    await order(session, clock, text="Same words", request_id="r2")

    assert [message_text(m.reason) for m in await _messages(session)] == ["Same words"] * 2


async def test_without_a_ceo_nothing_is_stored_or_sent(
    session: AsyncSession, clock: FakeClock
) -> None:
    answer = await order(session, clock, text=WORDS, request_id="r1")

    assert answer == "Nothing was sent. Assign the CEO in the CEO tab first."
    assert await _messages(session) == []
    assert await _count(session, CallRequest) == 0


async def test_an_empty_order_sends_nothing(
    session: AsyncSession, clock: FakeClock, ceo_id: int
) -> None:
    answer = await order(session, clock, text="  ", request_id="r1")

    assert answer == "I did not hear the order."
    assert await _messages(session) == []


async def test_a_malformed_request_id_is_rejected(session: AsyncSession, clock: FakeClock) -> None:
    with pytest.raises(ValueError, match="request_id"):
        await order(session, clock, text="x", request_id="a\nb")


async def test_a_merge_order_needs_its_project(session: AsyncSession, clock: FakeClock) -> None:
    answer = await order(session, clock, text="", request_id="r1", merge=3)

    assert answer == "Say which project the task to merge is in."
