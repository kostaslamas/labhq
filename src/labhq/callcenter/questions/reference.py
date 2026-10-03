"""Spoken references to a question: question 7 is "Q7".

Private on purpose: the shared parser for spoken references lives with the Call Center
tools, and this module must not depend on it. Both agree on the `Q<id>` shape.
"""

import re

_REFERENCE = re.compile(r"\s*q\s*(\d+)\s*[.!?]?\s*", re.IGNORECASE)


class InvalidReferenceError(ValueError):
    pass


def format_reference(question_id: int) -> str:
    return f"Q{question_id}"


def parse_reference(reference: str) -> int:
    match = _REFERENCE.fullmatch(reference)
    if match is None:
        raise InvalidReferenceError(f"not a question reference: {reference!r}")
    return int(match.group(1))
