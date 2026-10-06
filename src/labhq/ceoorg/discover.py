"""Find what the CEO could take over: folders under the allowed roots and CLI sessions.

Read-only. Hidden directories are never listed or entered, and a symlink is followed only
when it stays inside the roots, so a link planted in a project cannot lead the CEO out.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from labhq.adapters.tmux import default_kinds
from labhq.adoption.discovery import RunningAgent
from labhq.adoption.saved import SavedSession, list_saved_sessions
from labhq.work import WorkError


@dataclass(frozen=True)
class Folder:
    path: Path
    git: bool
    # The name of the project that already has this folder, if any.
    project: str | None


@dataclass(frozen=True)
class FolderSessions:
    folder: Path
    sessions: tuple[SavedSession, ...]


@dataclass(frozen=True)
class Discovery:
    folders: tuple[Folder, ...]
    running: tuple[RunningAgent, ...]
    saved: tuple[FolderSessions, ...]
    truncated: bool


def resolve_roots(configured: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    for path in configured:
        root = path.expanduser().resolve()
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def within(path: Path, roots: Iterable[Path]) -> Path | None:
    return next((root for root in roots if path == root or root in path.parents), None)


def check_root(requested: Path | None, roots: list[Path]) -> list[Path]:
    """The folders to scan: the allowed roots, or `requested` when it lies inside one."""
    if requested is None:
        return roots
    try:
        resolved = requested.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise WorkError(f"{requested} is not an existing directory") from None
    root = within(resolved, roots)
    if root is None:
        allowed = ", ".join(str(r) for r in roots) or "none"
        raise WorkError(f"{requested} is outside the allowed roots ({allowed})")
    if any(part.startswith(".") for part in resolved.relative_to(root).parts):
        raise WorkError(f"{requested} is a hidden directory")
    return [resolved]


def _children(directory: Path, roots: list[Path]) -> list[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name.casefold())
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            target = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if target.is_dir() and within(target, roots) is not None:
            found.append(target)
    return found


def scan_folders(
    starts: list[Path], roots: list[Path], *, depth: int, limit: int, registered: dict[Path, str]
) -> tuple[list[Folder], bool]:
    """Folders below `starts`, breadth first. A git repository is a leaf: it is the project."""
    folders: list[Folder] = []
    seen: set[Path] = set()
    level = starts
    for _ in range(depth):
        following: list[Path] = []
        for directory in level:
            for child in _children(directory, roots):
                if child in seen:
                    continue
                seen.add(child)
                if len(folders) >= limit:
                    return folders, True
                git = (child / ".git").exists()
                folders.append(Folder(child, git, registered.get(child)))
                if not git:
                    following.append(child)
        level = following
    return folders, False


def saved_sessions(folders: Iterable[Path], limit: int) -> list[FolderSessions]:
    """Resumable conversations per folder, for every CLI kind that can resume one."""
    found: list[FolderSessions] = []
    for folder in folders:
        sessions: list[SavedSession] = []
        for name in default_kinds.names():
            sessions.extend(list_saved_sessions(name, folder))
        if sessions:
            found.append(FolderSessions(folder, tuple(sessions)))
        if len(found) >= limit:
            break
    return found


def render(discovery: Discovery) -> str:
    lines = ["Folders:"]
    for folder in discovery.folders:
        kind = "git repository" if folder.git else "folder"
        taken = f", project {folder.project}" if folder.project else ""
        lines.append(f"- {folder.path} ({kind}{taken})")
    if not discovery.folders:
        lines.append("- none")
    if discovery.truncated:
        lines.append("(more folders exist; give a deeper `root` to see them)")
    lines.append("Running CLI sessions:")
    lines.extend(f"- pid {agent.pid}: {agent.kind} in {agent.cwd}" for agent in discovery.running)
    if not discovery.running:
        lines.append("- none")
    lines.append("Saved CLI sessions:")
    for entry in discovery.saved:
        lines.extend(
            f"- {entry.folder}: {session.kind} {session.session_id}" for session in entry.sessions
        )
    if not discovery.saved:
        lines.append("- none")
    return "\n".join(lines)
