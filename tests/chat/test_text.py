"""Long posts split into ordered parts at line, sentence or word boundaries."""

import pytest

from labhq.chat import split_message
from labhq.chat.contract import LONG_MESSAGE_LENGTH, long_message


def test_a_4500_character_message_becomes_ordered_parts_of_at_most_2000() -> None:
    text = long_message()
    assert len(text) == LONG_MESSAGE_LENGTH == 4500

    parts = split_message(text, 2000)

    assert len(parts) == 3
    assert "".join(parts) == text
    assert all(len(part) <= 2000 for part in parts)
    # The text has line breaks, so every cut but the last lands right after one.
    assert all(part.endswith("\n") for part in parts[:-1])


def test_without_line_breaks_the_cut_falls_after_a_sentence() -> None:
    text = "One short sentence. " * 150
    parts = split_message(text, 2000)
    assert "".join(parts) == text
    assert all(part.endswith(". ") for part in parts[:-1])


def test_a_sentence_end_beats_a_word_gap() -> None:
    assert split_message("Aa bb. Cc dd ee", 12) == ["Aa bb. ", "Cc dd ee"]


def test_a_word_gap_is_used_when_there_is_no_sentence_end() -> None:
    assert split_message("alpha beta gamma", 12) == ["alpha beta ", "gamma"]


def test_an_unbroken_run_is_cut_at_the_limit() -> None:
    assert split_message("x" * 5, 2) == ["xx", "xx", "x"]


def test_short_and_empty_messages_are_one_part() -> None:
    assert split_message("hi", 2000) == ["hi"]
    assert split_message("", 2000) == [""]


def test_the_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        split_message("x", 0)
