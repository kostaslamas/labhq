"""What the page shows for a project found in the roots: where, which kind, last commit."""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import Project
from labhq.inventory.git import Command, run_command
from labhq.inventory.model import FoundProject
from labhq.inventory.scope import real


@dataclass(frozen=True)
class FoundView:
    path: str
    name: str
    # The path below the scan root it was found under.
    relative: str
    markers: tuple[str, ...]
    last_commit_at: datetime | None


async def not_yet_added(db: AsyncSession, found: list[FoundProject]) -> list[FoundProject]:
    """Drop what labhq already has as a project, compared on the real path."""
    added = {real(path) for path in await db.scalars(select(Project.repo_path))}
    return [project for project in found if real(project.root) not in added]


def last_commit(folder: Path, *, timeout: float, command: Command = run_command) -> datetime | None:
    """The date of the newest commit, if git can say; a folder without a repository has none."""
    out = command(["git", "log", "-1", "--format=%cI"], folder, timeout)
    try:
        return datetime.fromisoformat(out.strip()) if out and out.strip() else None
    except ValueError:
        return None


def view(project: FoundProject, *, timeout: float, command: Command = run_command) -> FoundView:
    return FoundView(
        path=str(project.root),
        name=project.root.name,
        relative=os.path.relpath(project.root, project.under),
        markers=project.markers,
        last_commit_at=last_commit(project.root, timeout=timeout, command=command),
    )
