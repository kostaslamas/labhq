"""What a task hands in, as a registry: a new deliverable type is a registration.

`branch` is today's flow (a worktree, review, a merge approval). The others never touch git:
a `document` is a file in the department folder, a `report` or a `decision` is text that
travels up through the review flow like any report.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from labhq.approvals.registry import Registry
from labhq.work.service import WorkError

BRANCH = "branch"
DOCUMENT = "document"
REPORT = "report"
DECISION = "decision"

DOCUMENTS_DIRECTORY = "documents"
DEFAULT_DOCUMENT_NAME = "document.md"
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


@dataclass(frozen=True)
class Deliverable:
    key: str
    description: str
    # Only a branch deliverable is worked on in a git worktree.
    uses_worktree: bool = False
    # A file must exist in the department folder before the task can be reported ready.
    needs_document: bool = False


default_deliverables = Registry[Deliverable]("deliverable type")
for _deliverable in (
    Deliverable(BRANCH, "a branch of the project, merged after the owner approves", True),
    Deliverable(DOCUMENT, "a file in the department folder", needs_document=True),
    Deliverable(REPORT, "a written report"),
    Deliverable(DECISION, "a decision with its reasons"),
):
    default_deliverables.register(_deliverable.key, _deliverable)


def document_path(folder: Path, task_id: int, name: str) -> Path:
    """Where a task's document goes; a name that could leave the folder is refused."""
    if not _SAFE_NAME.fullmatch(name):
        raise WorkError(
            f"{name!r} is not a plain file name: use letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return folder / DOCUMENTS_DIRECTORY / f"T{task_id}-{name}"


def has_document(folder: Path, reference: str | None) -> bool:
    if reference is None:
        return False
    target = (folder / reference).resolve()
    return target.is_relative_to(folder.resolve()) and target.is_file()
