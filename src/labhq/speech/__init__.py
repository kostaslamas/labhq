"""Text that is safe to read aloud: rules and spoken-form helpers."""

from labhq.speech.rules import (
    SpeechError,
    join_sentences,
    say_ago,
    say_count,
    say_micros,
    speakable,
)

__all__ = [
    "SpeechError",
    "join_sentences",
    "say_ago",
    "say_count",
    "say_micros",
    "speakable",
]
