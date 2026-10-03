"""Spoken references: short handles the owner can say back to `decide` and `answer`."""

import re
from typing import Literal

RefKind = Literal["approval", "question"]

# One letter per kind keeps a reference short enough to say and to hear.
_PREFIXES: dict[RefKind, str] = {"approval": "A", "question": "Q"}
_KIND_BY_LETTER: dict[str, RefKind] = {letter: kind for kind, letter in _PREFIXES.items()}
_REF = re.compile(rf"^\s*([{''.join(_KIND_BY_LETTER)}])[\s#-]*(\d+)\s*[.!?]?\s*$", re.IGNORECASE)


def approval_ref(approval_id: int) -> str:
    return f"{_PREFIXES['approval']}{approval_id}"


def question_ref(question_id: int) -> str:
    return f"{_PREFIXES['question']}{question_id}"


def parse_ref(text: str) -> tuple[RefKind, int]:
    """Read "A12", "a 12" or "q7." back into a kind and an id; raise `ValueError` otherwise."""
    match = _REF.match(text)
    if match is None:
        raise ValueError(f"not a reference: {text!r}")
    return _KIND_BY_LETTER[match.group(1).upper()], int(match.group(2))
