import pytest

from labhq.callcenter.questions import InvalidReferenceError, format_reference, parse_reference


@pytest.mark.parametrize("spoken", ["Q7", "q7", " Q 7 ", "Q7."])
def test_a_spoken_reference_names_its_question(spoken: str) -> None:
    assert parse_reference(spoken) == 7


def test_a_reference_round_trips() -> None:
    assert parse_reference(format_reference(42)) == 42


@pytest.mark.parametrize("spoken", ["", "7", "Q", "question seven", "Q7 and Q8", "Qx"])
def test_anything_else_is_refused(spoken: str) -> None:
    with pytest.raises(InvalidReferenceError):
        parse_reference(spoken)
