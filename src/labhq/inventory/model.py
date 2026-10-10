"""What a scan finds: sessions, the projects they belong to, and what to do with them."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class SessionState(StrEnum):
    RUNNING = "running"
    WAITING = "waiting for input"
    # No process: a saved conversation, or a running agent that has been quiet.
    IDLE = "idle"


class Action(StrEnum):
    CONTINUE = "continue"
    CLOSE = "close"
    HISTORY = "keep as history"


@dataclass(frozen=True)
class SavedEntry:
    """One conversation in a tool's local store: ids, folder and time only, never text."""

    tool: str
    session_id: str
    folder: Path
    updated_at: datetime
    # Where the transcript lives, so an analysis the owner asked for can read its tail.
    location: Path | None = None


@dataclass(frozen=True)
class SessionInfo:
    tool: str
    session_id: str | None
    folder: Path
    state: SessionState
    last_activity: datetime | None
    idle_seconds: float | None
    # The process of a running agent; None for a saved conversation.
    pid: int | None = None
    started_at: float | None = None
    location: Path | None = None
    # Whether labhq can continue it itself; Cursor IDE work is handed off instead.
    resumable: bool = True


@dataclass(frozen=True)
class GitFacts:
    branch: str | None = None
    dirty_files: int = 0
    last_commit_subject: str | None = None
    last_commit_at: datetime | None = None
    open_pr: str | None = None


@dataclass(frozen=True)
class Proposal:
    action: Action
    reason: str


@dataclass
class ProjectInventory:
    root: Path
    name: str
    has_repo: bool
    git: GitFacts = field(default_factory=GitFacts)
    sessions: list[SessionInfo] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)


@dataclass(frozen=True)
class ToolStatus:
    tool: str
    # None when the tool has no status command or it could not be run.
    logged_in: bool | None
    account: str | None = None
    # "allow" / "warn" / "stop" from the plan check; None when no reading exists.
    plan: str | None = None
    plan_used_percent: float | None = None


@dataclass(frozen=True)
class FolderProposal:
    """A parent folder that holds several projects: one manager could look after them."""

    folder: Path
    projects: tuple[Path, ...]


@dataclass(frozen=True)
class FoundProject:
    """A project folder inside the roots that no session points at."""

    root: Path
    under: Path
    markers: tuple[str, ...]


@dataclass
class Inventory:
    scanned_at: datetime
    projects: list[ProjectInventory] = field(default_factory=list)
    tools: list[ToolStatus] = field(default_factory=list)
    folders: list[FolderProposal] = field(default_factory=list)
    # The roots the scan used; empty when it was machine-wide.
    roots: tuple[Path, ...] = ()
    # Sessions the scope turned away, as a number only: their folders are not kept.
    left_out: int = 0
    # Projects found in the roots that have no session (merged by real path with `projects`).
    found: list[FoundProject] = field(default_factory=list)
    folders_visited: int = 0
    # True when the folder cap stopped the discovery walk.
    discovery_capped: bool = False
