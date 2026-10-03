"""Rules that keep tool output speakable, and helpers that phrase numbers for the ear."""

import re
from dataclasses import dataclass
from datetime import timedelta

from labhq.speech.settings import get_speech_settings

MICROS_PER_CENT = 10_000
CENTS_PER_DOLLAR = 100


class SpeechError(ValueError):
    """The text contains something a voice cannot read; the message names the rule."""


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    reason: str


# Data, not branches: a new rejected shape is a new row here.
RULES: tuple[Rule, ...] = (
    Rule(
        "code_fence",
        re.compile(r"^\s*(```|~~~)", re.MULTILINE),
        "code fences cannot be read aloud",
    ),
    Rule(
        "table_separator",
        re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", re.MULTILINE),
        "markdown tables cannot be read aloud",
    ),
    Rule(
        "pipe_row",
        re.compile(r"^[^\n]*\|[^\n]*$", re.MULTILINE),
        "markdown tables cannot be read aloud",
    ),
    Rule("heading", re.compile(r"^\s*#{1,6}\s", re.MULTILINE), "headings cannot be read aloud"),
    Rule(
        "list_item",
        re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S", re.MULTILINE),
        "list lines cannot be read aloud",
    ),
    Rule(
        "json",
        re.compile(r'\{\s*"[^"\n]*"\s*:|\{\s*\}|\[\s*(?:\{|"[^"\n]*"\s*[,\]]|-?\d+\s*[,\]])'),
        "JSON cannot be read aloud",
    ),
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def speakable(text: str) -> str:
    """Return `text` unchanged if a voice can read it; raise `SpeechError` otherwise."""
    for rule in RULES:
        if rule.pattern.search(text):
            raise SpeechError(f"{rule.name}: {rule.reason}")
    limit = get_speech_settings().max_sentence_words
    for sentence in _SENTENCE_BREAK.split(text):
        words = len(sentence.split())
        if words > limit:
            raise SpeechError(f"sentence_too_long: {words} words, the limit is {limit}")
    return text


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


def say_micros(micros: int) -> str:
    """Phrase an amount in micro-USD, rounded to the nearest cent."""
    if micros <= 0:
        return "nothing"
    cents_total = (micros + MICROS_PER_CENT // 2) // MICROS_PER_CENT
    if cents_total == 0:
        return "less than a cent"
    dollars, cents = divmod(cents_total, CENTS_PER_DOLLAR)
    cents_part = f"{cents} {_plural(cents, 'cent')}"
    if dollars == 0:
        return cents_part
    dollars_part = f"{dollars} {_plural(dollars, 'dollar')}"
    return dollars_part if cents == 0 else f"{dollars_part} and {cents_part}"


def say_count(n: int, noun: str, plural: str | None = None) -> str:
    many = plural if plural is not None else f"{noun}s"
    if n == 0:
        return f"no {many}"
    if n == 1:
        return f"one {noun}"
    return f"{n} {many}"


# Largest span first; the first unit the delta reaches wins.
_AGO_UNITS: tuple[tuple[str, int], ...] = (
    ("day", 86_400),
    ("hour", 3_600),
    ("minute", 60),
)


def say_ago(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    for unit, size in _AGO_UNITS:
        if seconds >= size:
            amount = seconds // size
            return f"{amount} {_plural(amount, unit)} ago"
    return "just now"


def join_sentences(parts: list[str]) -> str:
    """Join fragments into prose, giving each a full stop so the voice pauses between them."""
    sentences = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        sentences.append(stripped if stripped[-1] in ".!?" else f"{stripped}.")
    return " ".join(sentences)
