"""Fixture stores in each tool's real on-disk layout (checked 2026-10-09; see the module
docstrings of `labhq.inventory.stores`). Every conversation carries SECRET_TEXT, which a scan
must never surface, and the Cursor stores carry a login token it must never select."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

SECRET_TEXT = "secret conversation text zz9"
SECRET_TOKEN = "SECRET-LOGIN-TOKEN"
EPOCH_MS = 1_780_000_000_000  # 2026-05-28, in milliseconds
CLAUDE_ID = "11111111-1111-4111-8111-111111111111"
CODEX_ID = "22222222-2222-4222-8222-222222222222"
GEMINI_ID = "33333333-3333-4333-8333-333333333333"


def claude(home: Path, folder: Path, session_id: str = CLAUDE_ID) -> Path:
    directory = home / ".claude" / "projects" / str(folder).replace("/", "-")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    rows = [{"type": "mode"}, {"cwd": str(folder), "type": "user", "message": SECRET_TEXT}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def codex(home: Path, folder: Path, session_id: str = CODEX_ID) -> Path:
    directory = home / ".codex" / "sessions" / "2026" / "10" / "01"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-10-01T10-00-00-{session_id}.jsonl"
    meta = {"type": "session_meta", "payload": {"id": session_id, "cwd": str(folder)}}
    text = {"type": "response_item", "payload": {"text": SECRET_TEXT}}
    path.write_text(json.dumps(meta) + "\n" + json.dumps(text) + "\n", encoding="utf-8")
    return path


def gemini(home: Path, folder: Path, session_id: str = GEMINI_ID) -> Path:
    directory = home / ".gemini" / "tmp" / "abc123"
    (directory / "chats").mkdir(parents=True, exist_ok=True)
    (directory / ".project_root").write_text(str(folder), encoding="utf-8")
    path = directory / "chats" / "session-2026-10-01T10-00-abc.json"
    document = {"sessionId": session_id, "messages": [{"content": SECRET_TEXT}]}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def aider(folder: Path) -> Path:
    path = folder / ".aider.chat.history.md"
    path.write_text(f"#### {SECRET_TEXT}\n", encoding="utf-8")
    return path


def opencode(
    home: Path,
    rows: list[tuple[str, str, str | None, int | None]],
) -> Path:
    """Rows are (id, directory, parent id or None, archived time or None)."""
    directory = home / ".local" / "share" / "opencode"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "opencode.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, "
            "directory TEXT, title TEXT, time_created INTEGER, time_updated INTEGER, "
            "time_archived INTEGER)"
        )
        db.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, data TEXT)")
        for index, (session_id, folder, parent, archived) in enumerate(rows):
            db.execute(
                "INSERT INTO session VALUES (?, 'p', ?, ?, ?, ?, ?, ?)",
                (session_id, parent, folder, SECRET_TEXT, EPOCH_MS, EPOCH_MS + index, archived),
            )
            db.execute(
                "INSERT INTO message VALUES (?, ?, ?)", (f"m{index}", session_id, SECRET_TEXT)
            )
        db.commit()
    return path


def cursor_cli(
    home: Path, chat_id: str, meta: dict[str, object] | None, *, store: bool = True
) -> Path:
    directory = home / ".cursor" / "chats" / "5d41402abc4b2a76b9719d911017c592" / chat_id
    directory.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if store:
        with closing(sqlite3.connect(directory / "store.db")) as db:
            db.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO blobs VALUES ('a', ?)", (SECRET_TEXT.encode(),))
            db.execute("INSERT INTO meta VALUES ('0', ?)", (SECRET_TOKEN,))
            db.commit()
    return directory


def cursor_ide(
    home: Path, chats: dict[str, tuple[Path | None, int]], *, legacy: Path | None = None
) -> Path:
    """Cursor 3 layout: the chat index is in the global database; `chats` maps a composer id
    to (workspace folder, last update in ms). `legacy` adds a pre-3.0 workspace database."""
    user = home / ".config" / "Cursor" / "User"
    (user / "globalStorage").mkdir(parents=True, exist_ok=True)
    path = user / "globalStorage" / "state.vscdb"
    headers = {
        "allComposers": [
            {
                "composerId": composer_id,
                "name": SECRET_TEXT,
                "workspaceIdentifier": (
                    {"id": "w", "uri": {"fsPath": str(folder), "scheme": "file"}} if folder else {}
                ),
            }
            for composer_id, (folder, _) in chats.items()
        ]
    }
    with closing(sqlite3.connect(path)) as db:
        _kv_tables(db)
        db.execute(
            "INSERT INTO ItemTable VALUES ('composer.composerHeaders', ?)", (json.dumps(headers),)
        )
        db.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', ?)", (SECRET_TOKEN,))
        for composer_id, (_, updated) in chats.items():
            data = {"composerId": composer_id, "createdAt": EPOCH_MS, "lastUpdatedAt": updated}
            db.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"composerData:{composer_id}", json.dumps(data)),
            )
            db.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"bubbleId:{composer_id}:b1", SECRET_TEXT),
            )
        db.commit()
    if legacy is not None:
        workspace = user / "workspaceStorage" / "hash1"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "workspace.json").write_text(
            json.dumps({"folder": legacy.as_uri()}), encoding="utf-8"
        )
        old = {"allComposers": [{"composerId": "legacy-chat", "name": SECRET_TEXT}]}
        with closing(sqlite3.connect(workspace / "state.vscdb")) as db:
            _kv_tables(db)
            db.execute(
                "INSERT INTO ItemTable VALUES ('composer.composerData', ?)", (json.dumps(old),)
            )
            db.commit()
        with closing(sqlite3.connect(path)) as db:
            data = {
                "composerId": "legacy-chat",
                "createdAt": EPOCH_MS,
                "lastUpdatedAt": EPOCH_MS + 5,
            }
            db.execute(
                "INSERT INTO cursorDiskKV VALUES ('composerData:legacy-chat', ?)",
                (json.dumps(data),),
            )
            db.commit()
    return path


def _kv_tables(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE ItemTable (key TEXT UNIQUE, value BLOB)")
    db.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE, value BLOB)")
