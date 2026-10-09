"""Readers for tools that keep one file per conversation: Claude Code, Codex, Gemini, Aider.

Only the id, the folder and the file's modification time are taken. The first lines of a
file are parsed for the folder field alone; no message text is kept.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from labhq.inventory.model import SavedEntry
from labhq.inventory.stores.layout import StoreLayout, register_format

MAX_LINE = 131_072
HEAD_LINES = 256


def is_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _head(path: Path) -> Iterator[dict[str, object]]:
    with path.open(encoding="utf-8", errors="replace") as stream:
        for _ in range(HEAD_LINES):
            line = stream.readline(MAX_LINE + 1)
            if not line:
                return
            if len(line) > MAX_LINE:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _real_files(root: Path, pattern: str) -> Iterator[Path]:
    for path in root.glob(pattern):
        if not path.is_symlink() and path.is_file():
            yield path


@register_format("jsonl-cwd-field")
def jsonl_cwd_field(layout: StoreLayout, root: Path) -> Iterator[SavedEntry]:
    """Claude Code: `<projects>/<dir>/<uuid>.jsonl`; some row near the top has a `cwd`."""
    for path in _real_files(root, layout.options["glob"]):
        if not is_uuid(path.stem):
            continue
        for row in _head(path):
            cwd = row.get("cwd")
            if isinstance(cwd, str) and Path(cwd).is_absolute():
                yield SavedEntry(layout.tool, path.stem, Path(cwd), modified(path), path)
                break


@register_format("jsonl-meta-row")
def jsonl_meta_row(layout: StoreLayout, root: Path) -> Iterator[SavedEntry]:
    """Codex: `rollout-*.jsonl` whose first row is `session_meta` with `id` and `cwd`."""
    for path in _real_files(root, layout.options["glob"]):
        first = next(_head(path), {})
        meta = first.get("payload")
        if first.get("type") != "session_meta" or not isinstance(meta, dict):
            continue
        session_id, cwd = meta.get("id"), meta.get("cwd")
        if isinstance(session_id, str) and is_uuid(session_id) and isinstance(cwd, str):
            yield SavedEntry(layout.tool, session_id, Path(cwd), modified(path), path)


@register_format("gemini-marker")
def gemini_marker(layout: StoreLayout, root: Path) -> Iterator[SavedEntry]:
    """Gemini CLI: `<tmp>/<dir>/.project_root` names the folder; chats sit beside it."""
    for directory in root.iterdir():
        marker = directory / ".project_root"
        if directory.is_symlink() or not marker.is_file() or marker.is_symlink():
            continue
        folder = Path(marker.read_text(encoding="utf-8").strip())
        for path in _real_files(directory, layout.options["glob"]):
            with path.open("rb") as stream:
                header = stream.read(4096)
            match = re.search(rb'"sessionId"\s*:\s*"([^"]+)"', header)
            session_id = match.group(1).decode("ascii", errors="replace") if match else ""
            if is_uuid(session_id):
                yield SavedEntry(layout.tool, session_id, folder, modified(path), path)
