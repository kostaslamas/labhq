import pytest

from labhq.speech import SpeechError, speakable
from labhq.speech.settings import get_speech_settings

REJECTED = {
    "pipe_table": "Name | Cost\nalpha | 3\nbeta | 4",
    "table_separator": "|---|---|",
    "bordered_table": "| Name | Cost |\n|------|------|\n| alpha | 3 |",
    "code_fence": "Run this:\n```\nls\n```",
    "tilde_fence": "~~~\nls\n~~~",
    "heading": "# Status\nAll good.",
    "subheading": "Intro.\n### Details",
    "json_object": 'The state is {"agent": 3, "ok": true}.',
    "json_array_of_objects": 'Items: [{"id": 1}]',
    "json_array_of_numbers": "Values: [1, 2, 3]",
    "dash_bullet": "Today:\n- fixed the bug",
    "star_bullet": "* fixed the bug",
    "numbered_list": "1. First\n2. Second",
    "numbered_paren": "1) First",
}

ACCEPTED = {
    "plain": "You have two approvals waiting.",
    "numbers_in_prose": "The agent finished 3 tasks in 2 hours.",
    "hyphen_inside_text": "The worker is re-running its tests - it should take a minute.",
    "year_not_a_list": "In 2026. Things went well.",
    "empty": "",
    "multiple_sentences": "Done. The branch is pushed! Anything else?",
    "single_pipe": "Use a pipe to chain commands.",
    "brackets_in_prose": "The result [see below] is fine.",
}


@pytest.mark.parametrize("text", REJECTED.values(), ids=REJECTED.keys())
def test_unspeakable_text_is_rejected(text: str) -> None:
    with pytest.raises(SpeechError):
        speakable(text)


@pytest.mark.parametrize("text", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_speakable_text_is_returned_unchanged(text: str) -> None:
    assert speakable(text) == text


def test_rejection_names_the_rule() -> None:
    with pytest.raises(SpeechError, match="heading"):
        speakable("# Title")


def test_sentence_at_the_limit_passes_and_one_over_fails() -> None:
    limit = get_speech_settings().max_sentence_words
    assert speakable(" ".join(["word"] * limit) + ".")
    with pytest.raises(SpeechError, match="sentence_too_long"):
        speakable(" ".join(["word"] * (limit + 1)) + ".")


def test_limit_applies_per_sentence_not_per_text() -> None:
    limit = get_speech_settings().max_sentence_words
    sentence = " ".join(["word"] * (limit - 1)) + "."
    assert speakable(f"{sentence} {sentence}")


def test_limit_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "labhq.speech.rules.get_speech_settings",
        lambda: type("S", (), {"max_sentence_words": 3})(),
    )
    with pytest.raises(SpeechError):
        speakable("one two three four.")
