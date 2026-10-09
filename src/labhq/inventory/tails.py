"""The tail of one transcript: the only place conversation text is read.

It runs for an analysis the owner asked for on one project (the request is the consent) and
only for the sessions of that project. Each tool's reader is a registry entry; a tool whose
store cannot be read as text (Cursor CLI keeps an opaque blob store) returns nothing and the
analysis says so. A reader never opens a credential file: it is handed the transcript's own
path.
"""

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

from labhq.inventory.model import SavedEntry
from labhq.inventory.stores.opencode import connect_read_only

# (entry, max characters) -> the last characters of the conversation.
TailReader = Callable[[SavedEntry, int], str]
TAIL_BYTES = 262_144
ROWS = 40


def _leaf_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaf_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaf_strings(item)


def _last_bytes(path: Path) -> str:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - TAIL_BYTES))
        return stream.read().decode("utf-8", errors="replace")


def jsonl_tail(entry: SavedEntry, limit: int) -> str:
    if entry.location is None:
        return ""
    texts: list[str] = []
    for line in _last_bytes(entry.location).splitlines()[1:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        texts.extend(
            s for s in _leaf_strings(row.get("message", row.get("payload", row))) if " " in s
        )
    return "\n".join(texts)[-limit:]


def json_document_tail(entry: SavedEntry, limit: int) -> str:
    if entry.location is None:
        return ""
    try:
        document = json.loads(entry.location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    messages = document.get("messages", []) if isinstance(document, dict) else []
    return "\n".join(_leaf_strings(messages[-ROWS:]))[-limit:]


def text_tail(entry: SavedEntry, limit: int) -> str:
    return _last_bytes(entry.location)[-limit:] if entry.location else ""


def _sql_tail(entry: SavedEntry, limit: int, query: str, argument: str) -> str:
    if entry.location is None:
        return ""
    try:
        with closing(connect_read_only(entry.location)) as connection:
            rows = connection.execute(query, (argument, ROWS)).fetchall()
    except sqlite3.Error:
        return ""
    return "\n".join(str(row[0]) for row in reversed(rows) if row[0])[-limit:]


def opencode_tail(entry: SavedEntry, limit: int) -> str:
    # `part.data` is JSON; text parts carry `text`. Unchecked against a live install.
    query = (
        "SELECT json_extract(data, '$.text') FROM part WHERE session_id = ? "
        "ORDER BY rowid DESC LIMIT ?"
    )
    return _sql_tail(entry, limit, query, entry.session_id)


def cursor_ide_tail(entry: SavedEntry, limit: int) -> str:
    query = (
        "SELECT json_extract(value, '$.text') FROM cursorDiskKV WHERE key LIKE ? "
        "ORDER BY rowid DESC LIMIT ?"
    )
    return _sql_tail(entry, limit, query, f"bubbleId:{entry.session_id}:%")


def unreadable(entry: SavedEntry, limit: int) -> str:
    return ""


TAIL_READERS: dict[str, TailReader] = {
    "claude-code": jsonl_tail,
    "codex": jsonl_tail,
    "gemini": json_document_tail,
    "aider": text_tail,
    "opencode": opencode_tail,
    "cursor-ide": cursor_ide_tail,
    "cursor-agent": unreadable,
}


def tail_of(entry: SavedEntry, limit: int) -> str:
    reader = TAIL_READERS.get(entry.tool, unreadable)
    try:
        return reader(entry, limit)
    except OSError:
        return ""
