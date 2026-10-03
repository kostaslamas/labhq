import pytest

from labhq.callcenter.answers.refs import approval_ref, parse_ref, question_ref


def test_references_are_spoken_forms() -> None:
    assert approval_ref(12) == "A12"
    assert question_ref(7) == "Q7"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A12", ("approval", 12)),
        ("a 12", ("approval", 12)),
        ("  q7 ", ("question", 7)),
        ("Q 007", ("question", 7)),
        ("a-3", ("approval", 3)),
    ],
)
def test_parse_is_case_insensitive_and_tolerates_spaces(
    text: str, expected: tuple[str, int]
) -> None:
    assert parse_ref(text) == expected


@pytest.mark.parametrize("text", ["", "12", "X1", "A", "A1B", "approval 12"])
def test_parse_rejects_what_is_not_a_reference(text: str) -> None:
    with pytest.raises(ValueError, match="not a reference"):
        parse_ref(text)


def test_round_trip() -> None:
    assert parse_ref(approval_ref(41)) == ("approval", 41)
    assert parse_ref(question_ref(2)) == ("question", 2)
