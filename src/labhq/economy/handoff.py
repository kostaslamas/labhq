"""Structured handoffs between agents, rendered as terse text with fields in a fixed order."""

import re

from pydantic import BaseModel, ConfigDict, Field

EMPTY = "-"
_LIST_SEPARATOR = "; "
_WHITESPACE = re.compile(r"\s+")


class Handoff(BaseModel):
    """What one agent leaves for the next. Field order here is the rendered order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(min_length=1)
    done: tuple[str, ...] = ()
    next: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    # Branches, commits, task ids, paths: anything the reader can look up instead of reread.
    refs: tuple[str, ...] = ()


def _one_line(text: str) -> str:
    # A newline inside a value would break the one-field-per-line structure.
    return _WHITESPACE.sub(" ", text).strip()


def _render_value(value: str | tuple[str, ...]) -> str:
    items = [value] if isinstance(value, str) else list(value)
    cleaned = [line for line in (_one_line(item) for item in items) if line]
    return _LIST_SEPARATOR.join(cleaned) or EMPTY


def render_handoff(handoff: Handoff) -> str:
    """One `field: value` line per field, every field present, in declaration order."""
    return "\n".join(
        f"{name}: {_render_value(getattr(handoff, name))}" for name in Handoff.model_fields
    )
