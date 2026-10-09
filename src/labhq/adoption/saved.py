"""List resumable CLI conversations for one exact project directory.

Only session ids, timestamps and working-directory metadata are read. Conversation
messages are never returned to the browser. Each CLI has its own local store layout.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from labhq.adapters.tmux import default_kinds


@dataclass(frozen=True)
class SavedSession:
    kind: str
    session_id: str
    updated_at: datetime


def _uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _claude_cwd(path: Path) -> Path | None:
    # Claude files can begin with mode or bridge records before their first cwd.
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for _ in range(256):
                line = stream.readline(131_073)
                if not line:
                    break
                if len(line) > 131_072:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str) and Path(cwd).is_absolute():
                    return Path(cwd).resolve()
    except OSError:
        return None
    return None


def _claude(project: Path, home: Path) -> list[SavedSession]:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "projects"
    directory = base / str(project).replace("/", "-")
    if not directory.is_dir():
        return []
    found = []
    for path in directory.glob("*.jsonl"):
        if path.is_symlink() or not _uuid(path.stem) or _claude_cwd(path) != project:
            continue
        found.append(SavedSession("claude-code", path.stem, _modified(path)))
    return found


def _codex(project: Path, home: Path) -> list[SavedSession]:
    base = Path(os.environ.get("CODEX_HOME", home / ".codex")) / "sessions"
    if not base.is_dir():
        return []
    found = []
    for path in base.rglob("rollout-*.jsonl"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                first = stream.readline(131_073)
            if len(first) > 131_072:
                continue
            row = json.loads(first)
            meta = row.get("payload", {}) if row.get("type") == "session_meta" else {}
            session_id, cwd = meta.get("id"), meta.get("cwd")
            if (
                not isinstance(session_id, str)
                or not _uuid(session_id)
                or not isinstance(cwd, str)
                or Path(cwd).resolve() != project
            ):
                continue
            found.append(SavedSession("codex", session_id, _modified(path)))
        except (OSError, ValueError, AttributeError):
            continue
    return found


def _gemini(project: Path, home: Path) -> list[SavedSession]:
    base = Path(os.environ.get("GEMINI_CLI_HOME", home / ".gemini")) / "tmp"
    if not base.is_dir():
        return []
    found = []
    for directory in base.iterdir():
        marker = directory / ".project_root"
        if directory.is_symlink() or not marker.is_file() or marker.is_symlink():
            continue
        try:
            if Path(marker.read_text(encoding="utf-8").strip()).resolve() != project:
                continue
        except (OSError, ValueError):
            continue
        for path in (directory / "chats").glob("session-*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                # The UUID is recorded in the filename suffix and confirmed in the file.
                with path.open("rb") as stream:
                    header = stream.read(4096)
                match = re.search(rb'"sessionId"\s*:\s*"([^"]+)"', header)
                session_id = match.group(1).decode("ascii") if match else ""
                if _uuid(session_id):
                    found.append(SavedSession("gemini", session_id, _modified(path)))
            except (OSError, ValueError, AttributeError):
                continue
    return found


def _aider(project: Path) -> list[SavedSession]:
    path = project / ".aider.chat.history.md"
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        return []
    return [SavedSession("aider", path.name, _modified(path))]


def _aider_reader(project: Path, home: Path) -> list[SavedSession]:
    return _aider(project)


# Kinds whose store is read by directory here; every other kind is read through the
# machine-wide store layouts of `labhq.inventory.stores`, filtered to this folder.
_READERS = {
    "claude-code": _claude,
    "codex": _codex,
    "gemini": _gemini,
    "aider": _aider_reader,
}


def _store_sessions(kind: str, project: Path, home: Path) -> list[SavedSession]:
    from labhq.inventory.stores import Bases, Context, read_all

    entries = read_all(Context(Bases.for_user(home), os.environ), {kind})
    return [
        SavedSession(e.tool, e.session_id, e.updated_at)
        for e in entries
        if e.folder.resolve() == project
    ]


def list_saved_sessions(
    kind: str, project: Path, *, home: Path | None = None
) -> list[SavedSession]:
    """Return selectable sessions of a registered kind, newest first."""
    agent = default_kinds.get(kind)
    if agent.continue_selected is None:
        return []
    project = project.resolve()
    home = home or Path.home()
    reader = _READERS.get(kind)
    found = reader(project, home) if reader is not None else _store_sessions(kind, project, home)
    return sorted(found, key=lambda session: session.updated_at, reverse=True)


def find_saved_session(kind: str, project: Path, session_id: str) -> SavedSession:
    for session in list_saved_sessions(kind, project):
        if session.session_id == session_id:
            return session
    raise LookupError(f"session {session_id!r} is not available for {kind} in {project}")
