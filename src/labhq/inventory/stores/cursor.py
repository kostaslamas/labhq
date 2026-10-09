"""Cursor: the CLI's per-chat `meta.json`, and the IDE's SQLite chat index.

CLI: `chats/<workspace-hash>/<chat-id>/meta.json` carries `cwd` and `updatedAtMs`. The
sibling `store.db` holds the conversation and an encryption key, and is never opened.

IDE: both databases are `state.vscdb`. The global one also stores the login, so every query
names its keys: `composer.composerHeaders` (the index of chats with their workspace folder)
and `composerData:%` (two timestamps through `json_extract`). In the workspace database,
older versions keep `allComposers` under `composer.composerData`; it is read the same way.
No other key is selected.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from labhq.inventory.model import SavedEntry
from labhq.inventory.stores.files import modified
from labhq.inventory.stores.layout import StoreLayout, register_format
from labhq.inventory.stores.opencode import connect_read_only, from_millis

HEADERS_KEY = "composer.composerHeaders"
LEGACY_KEY = "composer.composerData"
TIMES = (
    "SELECT json_extract(value, '$.lastUpdatedAt'), json_extract(value, '$.createdAt') "
    "FROM cursorDiskKV WHERE key = ?"
)


def file_uri_path(uri: str) -> Path | None:
    """The local path of a `file://` URI; remote and workspace-file URIs are not folders."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _timestamp(value: object) -> datetime | None:
    """Milliseconds, microseconds or an RFC 3339 string, as different versions write them."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return from_millis(value / 1000 if value > 10**14 else value)


@register_format("cursor-cli-meta")
def cursor_cli_meta(layout: StoreLayout, root: Path) -> Iterator[SavedEntry]:
    for meta in root.glob(layout.options["glob"]):
        if meta.is_symlink() or not meta.is_file():
            continue
        try:
            document = json.loads(meta.read_text(encoding="utf-8"))
        except ValueError:
            continue
        cwd = document.get("cwd") if isinstance(document, dict) else None
        if not isinstance(cwd, str) or not document.get("hasConversation", True):
            continue
        when = _timestamp(document.get("updatedAtMs")) or modified(meta)
        yield SavedEntry(layout.tool, meta.parent.name, Path(cwd), when, meta.parent)


def _times(connection: sqlite3.Connection, composer_id: str) -> datetime | None:
    row = connection.execute(TIMES, (f"composerData:{composer_id}",)).fetchone()
    if row is None:
        return None
    return _timestamp(row[0]) or _timestamp(row[1])


def _json_value(connection: sqlite3.Connection, table: str, key: str) -> dict[str, object]:
    row = connection.execute(f"SELECT value FROM {table} WHERE key = ?", (key,)).fetchone()
    if row is None:
        return {}
    raw = row[0].decode("utf-8", errors="replace") if isinstance(row[0], bytes) else row[0]
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _headers(connection: sqlite3.Connection) -> Iterator[tuple[str, Path | None]]:
    composers = _json_value(connection, "ItemTable", HEADERS_KEY).get("allComposers")
    for header in composers if isinstance(composers, list) else []:
        if not isinstance(header, dict) or not isinstance(header.get("composerId"), str):
            continue
        identifier = header.get("workspaceIdentifier")
        uri = identifier.get("uri") if isinstance(identifier, dict) else None
        path = uri.get("fsPath") if isinstance(uri, dict) else None
        yield header["composerId"], Path(path) if isinstance(path, str) and path else None


def _workspace_folders(root: Path) -> Iterator[tuple[Path, Path]]:
    for workspace in root.glob("workspaceStorage/*/workspace.json"):
        try:
            folder = json.loads(workspace.read_text(encoding="utf-8")).get("folder")
        except (OSError, ValueError, AttributeError):
            continue
        path = file_uri_path(folder) if isinstance(folder, str) else None
        if path is not None:
            yield workspace.parent, path


@register_format("cursor-ide-vscdb")
def cursor_ide(layout: StoreLayout, root: Path) -> Iterator[SavedEntry]:
    global_db = root / "globalStorage" / "state.vscdb"
    if not global_db.is_file():
        return
    with closing(connect_read_only(global_db)) as connection:
        known: dict[str, Path | None] = dict(_headers(connection))
        # Cursor before 3.0 lists a workspace's chats in the workspace's own database.
        for directory, workspace_folder in _workspace_folders(root):
            database = directory / "state.vscdb"
            if not database.is_file():
                continue
            with closing(connect_read_only(database)) as workspace:
                legacy = _json_value(workspace, "ItemTable", LEGACY_KEY).get("allComposers")
            for item in legacy if isinstance(legacy, list) else []:
                if isinstance(item, dict) and isinstance(item.get("composerId"), str):
                    known.setdefault(item["composerId"], workspace_folder)
        for composer_id, folder in sorted(known.items()):
            when = _times(connection, composer_id)
            if folder is not None and when is not None:
                yield SavedEntry(layout.tool, composer_id, folder, when, global_db)
