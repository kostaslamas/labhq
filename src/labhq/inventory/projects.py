"""Sessions grouped into projects by the git root of their folder, and folder managers."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from labhq.inventory.git import git_root
from labhq.inventory.model import FolderProposal, ProjectInventory, SessionInfo

# The root a folder belongs to; swapped in tests so grouping needs no real checkout.
RootOf = Callable[[Path], Path | None]


def group_by_project(
    sessions: Iterable[SessionInfo], root_of: RootOf = git_root
) -> list[ProjectInventory]:
    """One project per git root; a folder without git is its own project, marked no repo."""
    roots: dict[Path, Path | None] = {}
    grouped: dict[Path, list[SessionInfo]] = defaultdict(list)
    for session in sessions:
        folder = session.folder.resolve()
        if folder not in roots:
            roots[folder] = root_of(folder)
        root = roots[folder]
        grouped[root or folder].append(session)
    projects = []
    for root in sorted(grouped):
        # A repo's projects are known by the walk above; a folder never seen as a root has none.
        repo = any(roots[s.folder.resolve()] is not None for s in grouped[root])
        ordered = sorted(grouped[root], key=_newest_first)
        projects.append(
            ProjectInventory(
                root=root, name=root.name or str(root), has_repo=repo, sessions=ordered
            )
        )
    return projects


def _newest_first(session: SessionInfo) -> tuple[float, str]:
    stamp = session.last_activity.timestamp() if session.last_activity else 0.0
    return (-stamp, session.tool)


def propose_folder_managers(
    projects: Iterable[ProjectInventory], *, minimum: int, home: Path | None = None
) -> list[FolderProposal]:
    """Parent folders that hold `minimum` or more projects.

    The owner's home directory and the filesystem root are never proposed: they hold
    projects by accident, not by arrangement.
    """
    skip = {Path("/"), (home or Path.home()).resolve()}
    by_parent: dict[Path, list[Path]] = defaultdict(list)
    for project in projects:
        by_parent[project.root.parent].append(project.root)
    return [
        FolderProposal(parent, tuple(sorted(members)))
        for parent, members in sorted(by_parent.items())
        if len(members) >= minimum and parent not in skip
    ]
