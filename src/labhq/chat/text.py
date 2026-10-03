"""Splitting long posts into parts a chat service accepts, at the most natural boundary."""

import re

# Tried in order: a paragraph or line break beats a sentence end, which beats a word gap.
_BOUNDARIES = (
    re.compile(r"\n"),
    re.compile(r"[.!?;](?=\s)\s*"),
    re.compile(r"\s+"),
)


def split_message(text: str, limit: int) -> list[str]:
    """Parts of at most `limit` characters whose concatenation is `text`, in order."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = _cut_point(rest, limit)
        parts.append(rest[:cut])
        rest = rest[cut:]
    if rest or not parts:
        parts.append(rest)
    return parts


def _cut_point(text: str, limit: int) -> int:
    window = text[:limit]
    for boundary in _BOUNDARIES:
        ends = [match.end() for match in boundary.finditer(window)]
        # A cut at the very start would make no progress.
        if ends and ends[-1] > 0:
            return ends[-1]
    return limit
