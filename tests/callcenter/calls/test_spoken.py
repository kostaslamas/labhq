import pytest

from labhq.callcenter.calls import to_speech
from labhq.callcenter.calls.spoken import SILENT, UNREADABLE
from labhq.speech import speakable


@pytest.mark.parametrize(
    "written",
    [
        "## Status\n- Worker: login form\n- Lead: reviewing",
        "| agent | doing |\n|---|---|\n| Worker | login form |",
        "**Worker** is on the `login form`.\n\n1. done markup\n2) next errors",
        "```\nlog line\n```\nWorker is on the login form",
        " ".join(["word"] * 95),
    ],
)
def test_written_text_becomes_speakable(written: str) -> None:
    spoken = to_speech(written)
    assert speakable(spoken) == spoken
    assert spoken not in (SILENT, UNREADABLE)


def test_plain_sentences_stay_as_they_are() -> None:
    text = "Worker is on the login form. It has no blockers."
    assert to_speech(text) == text


def test_json_is_replaced_by_a_sentence_that_says_so() -> None:
    assert to_speech('Here: {"agent": "Worker"}') == UNREADABLE


@pytest.mark.parametrize("empty", [None, "", "  \n"])
def test_no_answer_is_said_to_be_none(empty: str | None) -> None:
    assert to_speech(empty) == SILENT
