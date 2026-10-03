import pytest

from labhq.callcenter.status import StatusFields, parse_status, render_status
from labhq.callcenter.status.format import MAX_QUESTION_CHARS

FULL = """\
summary: Wiring the form.
done: markup; validation
next:
- error states
- tests
blockers: -
refs: labhq/task-1; 3f2a9c1
questions:
- Should a failed login lock the account?
- Which lifetime; hours or days?
"""


def test_a_full_file_parses_into_every_field() -> None:
    assert parse_status(FULL) == StatusFields(
        summary="Wiring the form.",
        done=("markup", "validation"),
        next=("error states", "tests"),
        refs=("labhq/task-1", "3f2a9c1"),
        questions=("Should a failed login lock the account?", "Which lifetime; hours or days?"),
    )


def test_render_then_parse_is_the_identity() -> None:
    fields = parse_status(FULL)
    assert parse_status(render_status(fields)) == fields


@pytest.mark.parametrize("text", ["", "   \n", "free text with no fields\n"])
def test_a_file_without_fields_parses_to_nothing(text: str) -> None:
    assert parse_status(text) == StatusFields()


def test_names_are_case_insensitive_and_markdown_decoration_is_ignored() -> None:
    fields = parse_status("## Summary: Hello\n**Done**: a\n`QUESTIONS`:\n1. One?\n* Two?\n")
    assert fields.summary == "Hello"
    assert fields.done == ("a",)
    assert fields.questions == ("One?", "Two?")


def test_an_unknown_line_continues_the_field_above() -> None:
    fields = parse_status("questions:\nDecision: A or B?\nnotes: more text\n")
    assert fields.questions == ("Decision: A or B?", "notes: more text")


def test_a_dash_means_nothing_and_a_repeated_field_adds() -> None:
    fields = parse_status("blockers: -\nrefs: a\nrefs: b\n")
    assert fields.blockers == ()
    assert fields.refs == ("a", "b")


def test_a_long_question_is_truncated() -> None:
    [question] = parse_status("questions: " + "x" * 5000).questions
    assert len(question) == MAX_QUESTION_CHARS
