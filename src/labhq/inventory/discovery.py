"""Find project folders inside the scan roots without opening a single file.

The walk reads directory entries only: names, and whether an entry is a folder. A folder
is a project when it holds a `.git` entry or a file named in `project_markers`; the walk then
stops there, so a project's subfolders are never separate projects (git submodules included).
Symlinks are never followed, hidden and heavy folders are skipped, exclusions are respected,
and the folders listed per walk are capped.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from labhq.inventory.model import FoundProject
from labhq.inventory.scope import Scope
from labhq.inventory.settings import InventorySettings

GIT_ENTRY = ".git"
GIT_LABEL = "git"


@dataclass(frozen=True)
class Discovery:
    projects: tuple[FoundProject, ...] = ()
    folders_visited: int = 0
    # True when the folder cap stopped the walk before it had seen everything.
    capped: bool = False


@dataclass
class _Walk:
    scope: Scope
    settings: InventorySettings
    found: dict[Path, FoundProject] = field(default_factory=dict)
    visited: int = 0
    capped: bool = False

    def run(self, root: Path) -> None:
        pending = [(root, 0)]
        while pending:
            folder, depth = pending.pop()
            if self.visited >= self.settings.discovery_max_folders:
                self.capped = True
                return
            self.visited += 1
            children = self._children(folder, depth)
            if children is None:
                continue
            markers, subfolders = children
            if markers:
                self.found.setdefault(folder, FoundProject(folder, root, tuple(markers)))
                continue
            pending.extend((child, depth + 1) for child in sorted(subfolders, reverse=True))

    def _children(self, folder: Path, depth: int) -> tuple[list[str], list[Path]] | None:
        markers: list[str] = []
        subfolders: list[Path] = []
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = entry.name
                    if name == GIT_ENTRY:
                        markers.append(GIT_LABEL)
                    elif name in self.settings.project_markers and not entry.is_dir(
                        follow_symlinks=False
                    ):
                        label = self.settings.project_markers[name]
                        if label not in markers:
                            markers.append(label)
                    elif self._may_descend(entry, depth):
                        subfolders.append(Path(entry.path))
        except OSError:
            return None
        return markers, subfolders

    def _may_descend(self, entry: os.DirEntry[str], depth: int) -> bool:
        if depth >= self.settings.discovery_depth:
            return False
        if entry.name.startswith(".") or entry.name in self.settings.discovery_skip_dirs:
            return False
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            return False
        return not self.scope.excluded(Path(entry.path))


def discover_projects(scope: Scope, settings: InventorySettings) -> Discovery:
    """Every project under the roots; nothing at all when no root is set."""
    walk = _Walk(scope, settings)
    for root in scope.roots:
        if root.is_dir() and not scope.excluded(root):
            walk.run(root)
    projects = tuple(sorted(walk.found.values(), key=lambda project: str(project.root)))
    return Discovery(projects, walk.visited, walk.capped)
