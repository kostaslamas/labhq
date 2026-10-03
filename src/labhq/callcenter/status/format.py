"""The `.labhq/status.md` format: what an agent writes, and a tolerant reader for it.

An agent keeps one small markdown file current in its worktree. Each field is a name, a
colon and a value, in any order:

    summary: Wiring the login form to the session API.
    done: form markup; validation
    next: error states
    blockers: -
    refs: labhq/task-12-login; 3f2a9c1
    questions:
    - Should a failed login lock the account?
    - Which session lifetime do we want?

Fields are the `labhq.economy.Handoff` fields plus `questions`. Rules the reader follows:

- Names are case-insensitive; surrounding `#`, `*` and backticks are ignored, so
  `## Summary` and `**summary**:` work.
- A value may continue on the following lines. `done`, `next`, `blockers` and `refs` split
  on `;` and on bullet lines; `questions` takes one question per line (a bullet marker is
  optional, a `;` is part of the question); `summary` joins its lines with a space.
- A line that is not a known field belongs to the field above it, so a question such as
  `Decision: A or B?` stays whole. Lines before the first field are ignored.
- `-` alone, or an empty value, means nothing.
- A missing or empty file parses to empty fields: an agent that has not reported yet is not
  an error. Repeating a field adds to it.
"""

import re
from collections.abc import Callable
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

MAX_QUESTION_CHARS: Final = 1000
_EMPTY = "-"
_LIST_SEPARATOR = "; "
_LIST_FIELDS = ("done", "next", "blockers", "refs")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FIELD = re.compile(r"^[\s#*`>]*([A-Za-z]+)[*`\s]*:(.*)$")
_WHITESPACE = re.compile(r"\s+")


class StatusFields(BaseModel):
    """A parsed status file. Field order is the rendered order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = ""
    done: tuple[str, ...] = ()
    next: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()


def _one_line(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _unbullet(line: str) -> str:
    return _BULLET.sub("", line, count=1)


def _list_items(lines: list[str]) -> tuple[str, ...]:
    parts = (_one_line(part) for line in lines for part in _unbullet(line).split(";"))
    return tuple(part for part in parts if part)


def _question_items(lines: list[str]) -> tuple[str, ...]:
    items = (_one_line(_unbullet(line)) for line in lines)
    return tuple(item[:MAX_QUESTION_CHARS] for item in items if item)


# Dispatch is data: how each field turns its raw lines into a value.
_READERS: dict[str, Callable[[list[str]], Any]] = {
    "summary": lambda lines: _one_line(" ".join(lines)),
    "questions": _question_items,
    **dict.fromkeys(_LIST_FIELDS, _list_items),
}


def _group_lines(text: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        match = _FIELD.match(raw)
        if match and match.group(1).lower() in _READERS and not _BULLET.match(raw):
            current = groups.setdefault(match.group(1).lower(), [])
            value = match.group(2).strip()
            if value:
                current.append(value)
        elif current is not None and raw.strip():
            current.append(raw.strip())
    return groups


def parse_status(text: str) -> StatusFields:
    """Read every known field from `text`; never raises on malformed input."""
    values = {
        name: _READERS[name]([line for line in lines if line != _EMPTY])
        for name, lines in _group_lines(text).items()
    }
    return StatusFields.model_validate(values)


def render_status(fields: StatusFields) -> str:
    """Write `fields` in the documented layout; `parse_status` reads it back unchanged."""
    lines = [f"summary: {fields.summary or _EMPTY}"]
    for name in _LIST_FIELDS:
        lines.append(f"{name}: {_LIST_SEPARATOR.join(getattr(fields, name)) or _EMPTY}")
    lines.append("questions:")
    lines += [f"- {question}" for question in fields.questions]
    return "\n".join(lines) + "\n"
