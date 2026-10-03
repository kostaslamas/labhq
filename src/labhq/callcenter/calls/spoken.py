"""Make the agent's reply safe to read aloud, whatever the model wrote.

The agent is told to answer in short spoken sentences, but a ticket's reply is checked
here, not trusted: markdown markers are dropped, list and table lines become sentences,
overlong sentences are cut, and anything `speakable` still refuses (JSON, for one) is
replaced by a sentence that says so.
"""

import re

from labhq.speech import SpeechError, speakable
from labhq.speech.settings import get_speech_settings

UNREADABLE = "The Call Center answered in a form I cannot read aloud. Please ask again."
SILENT = "The Call Center had nothing to say. Please ask again."

_FENCE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.MULTILINE)
_LINE_MARKER = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", re.MULTILINE)
_EMPHASIS = re.compile(r"[*_`]+")
_PIPE = re.compile(r"\s*\|\s*")
_ENDS_SENTENCE = re.compile(r"[.!?]$")


def _sentence(line: str) -> str:
    line = " ".join(line.split()).strip(" ,;")
    if not line:
        return ""
    return line if _ENDS_SENTENCE.search(line) else f"{line}."


def _cut(sentence: str, limit: int) -> list[str]:
    words = sentence.split()
    if len(words) <= limit:
        return [sentence]
    chunks = [" ".join(words[i : i + limit]) for i in range(0, len(words), limit)]
    return [_sentence(chunk) for chunk in chunks]


def to_speech(text: str | None) -> str:
    if text is None or not text.strip():
        return SILENT
    text = _FENCE.sub("", text)
    text = _TABLE_RULE.sub("", text)
    text = _LINE_MARKER.sub("", text)
    text = _PIPE.sub(", ", _EMPHASIS.sub("", text))
    limit = get_speech_settings().max_sentence_words
    sentences: list[str] = []
    for line in text.splitlines():
        for part in re.split(r"(?<=[.!?])\s+", line):
            sentence = _sentence(part)
            if sentence:
                sentences.extend(_cut(sentence, limit))
    spoken = " ".join(sentences)
    if not spoken:
        return SILENT
    try:
        return speakable(spoken)
    except SpeechError:
        return UNREADABLE
