"""Create a task by voice and wake its assignee, once per request id.

Idempotency needs no schema change. The wakeup key already dedupes per task, but a retry
arrives before anyone knows the task id, so the request id is stored as a marker line at the
end of the task description and looked up first. The check and the insert share one
transaction; two truly simultaneous retries on one request id are not serialised (there is
no unique constraint to lean on), which one voice session does not produce.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import Project, Task
from labhq.speech import join_sentences, speakable
from labhq.work import WorkError, add_task, find_project

MARKER_PREFIX = "voice-request:"
TITLE_LIMIT = 80
REASON = "ordered by voice"
_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


def _title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    if len(first_line) <= TITLE_LIMIT:
        return first_line
    return first_line[: TITLE_LIMIT - 1].rstrip() + "..."


async def _existing(db: AsyncSession, project_id: int, marker: str) -> Task | None:
    return await db.scalar(
        select(Task).where(
            Task.project_id == project_id,
            Task.description.endswith(marker, autoescape=True),
        )
    )


def _confirmation(task: Task, project: Project) -> str:
    parts = [f"Task T{task.id} created in {project.name}"]
    if task.assignee_id is not None:
        parts.append(f"It is assigned to agent {task.assignee_id}")
    return speakable(join_sentences(parts))


async def order(
    db: AsyncSession,
    clock: Clock,
    *,
    project: str,
    text: str,
    request_id: str,
    assignee: int | None = None,
) -> str:
    if not text.strip():
        return speakable("I did not hear what the task should be.")
    if not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must be 1 to 100 letters, digits or _ . : -")
    marker = f"{MARKER_PREFIX}{request_id}"
    try:
        owner = await find_project(db, project)
        existing = await _existing(db, owner.id, marker)
        if existing is not None:
            return _confirmation(existing, owner)
        task = await add_task(
            db,
            clock,
            project=project,
            title=_title(text),
            description=f"{text.strip()}\n\n{marker}",
            assignee=assignee,
            reason=REASON,
        )
    except WorkError as error:
        await db.rollback()
        return speakable(f"I could not create the task. {error}.")
    await db.commit()
    return _confirmation(task, owner)
