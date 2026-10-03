from datetime import timedelta

import pytest

from labhq.speech import join_sentences, say_ago, say_count, say_micros
from labhq.speech.settings import SpeechSettings


@pytest.mark.parametrize(
    ("micros", "spoken"),
    [
        (0, "nothing"),
        (1, "less than a cent"),
        (4_999, "less than a cent"),
        (10_000, "1 cent"),
        (120_000, "12 cents"),
        (1_000_000, "1 dollar"),
        (3_400_000, "3 dollars and 40 cents"),
        (1_010_000, "1 dollar and 1 cent"),
        (5_000_000, "5 dollars"),
    ],
)
def test_say_micros(micros: int, spoken: str) -> None:
    assert say_micros(micros) == spoken


@pytest.mark.parametrize(
    ("n", "spoken"), [(0, "no approvals"), (1, "one approval"), (3, "3 approvals")]
)
def test_say_count(n: int, spoken: str) -> None:
    assert say_count(n, "approval") == spoken


def test_say_count_uses_an_explicit_plural() -> None:
    assert say_count(2, "reply", "replies") == "2 replies"
    assert say_count(0, "reply", "replies") == "no replies"


@pytest.mark.parametrize(
    ("delta", "spoken"),
    [
        (timedelta(seconds=0), "just now"),
        (timedelta(seconds=59), "just now"),
        (timedelta(seconds=-5), "just now"),
        (timedelta(minutes=1), "1 minute ago"),
        (timedelta(minutes=5), "5 minutes ago"),
        (timedelta(hours=2), "2 hours ago"),
        (timedelta(days=3), "3 days ago"),
        (timedelta(hours=23, minutes=59), "23 hours ago"),
    ],
)
def test_say_ago(delta: timedelta, spoken: str) -> None:
    assert say_ago(delta) == spoken


def test_join_sentences_adds_stops_and_skips_blanks() -> None:
    assert join_sentences(["You have one approval", " ", "It is urgent!", "Shall I read it?"]) == (
        "You have one approval. It is urgent! Shall I read it?"
    )


def test_join_sentences_of_nothing_is_empty() -> None:
    assert join_sentences([]) == ""


def test_speech_settings_default() -> None:
    assert SpeechSettings().max_sentence_words == 40
