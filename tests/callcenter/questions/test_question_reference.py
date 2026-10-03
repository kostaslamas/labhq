import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.refs import parse_ref
from labhq.callcenter.questions import (
    AnswerError,
    InvalidReferenceError,
    answer,
    format_reference,
)
from labhq.clock import FakeClock
from tests.callcenter.factories import owner_request, scene


def test_a_reference_round_trips_through_the_shared_parser() -> None:
    assert parse_ref(format_reference(42)) == ("question", 42)


@pytest.mark.parametrize("spoken", ["Q7", "q7", " Q 7 ", "Q7."])
def test_spoken_forms_of_a_question_reference_are_understood(spoken: str) -> None:
    assert parse_ref(spoken) == ("question", 7)


@pytest.mark.parametrize("spoken", ["", "7", "Q", "question seven", "Q7 and Q8", "Qx", "A7"])
async def test_anything_else_is_refused_by_answer(
    session: AsyncSession, clock: FakeClock, spoken: str
) -> None:
    s = await scene(session, clock)
    await owner_request(session, clock, s.call_id, "req-1", "words")
    await session.commit()
    with pytest.raises(InvalidReferenceError):
        await answer(session, clock, spoken, call_id=s.call_id, request_id="req-1")
    assert issubclass(InvalidReferenceError, ValueError) and not issubclass(
        InvalidReferenceError, AnswerError
    )
