"""Create a task by voice and wake its assignee, once per request id; or ask for a merge.

A merge order only requests the heavy `merge` approval: the owner approves it with a
passkey and the engine merges, never this call (plan §5, rule 7).

Idempotency needs no schema change. The wakeup key already dedupes per task, but a retry
arrives before anyone knows the task id, so the request id is stored as a marker line at the
end of the task description and looked up first. The check and the insert share one
transaction; two truly simultaneous retries on one request id are not serialised (there is
no unique constraint to lean on), which one voice session does not produce.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.refs import approval_ref
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Project, Task
from labhq.hierarchy.roles import MANAGER
from labhq.speech import join_sentences, speakable
from labhq.work import WorkError, add_task, find_project, request_merge

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


async def _order_merge(db: AsyncSession, clock: Clock, project: str, task_id: int) -> str:
    # A retry finds the same pending approval, so the request id needs no marker here.
    try:
        owner = await find_project(db, project)
        task = await db.get(Task, task_id)
        if task is None or task.project_id != owner.id:
            raise WorkError(f"there is no task T{task_id} in {owner.name}")
        approval = await request_merge(db, clock, task.id)
    except WorkError as error:
        await db.rollback()
        return speakable(f"I could not request the merge. {error}.")
    target = approval.payload["target"]
    return speakable(
        f"Merging T{task.id} into {target} needs your approval, "
        f"so confirm {approval_ref(approval.id)} with your passkey."
    )


async def order(
    db: AsyncSession,
    clock: Clock,
    *,
    project: str,
    text: str,
    request_id: str,
    assignee: int | None = None,
    merge: int | None = None,
) -> str:
    """Create a task from `text`, or with `merge` set to a task id, request its merge."""
    if merge is not None:
        return await _order_merge(db, clock, project, merge)
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
        if assignee is None:
            manager = await db.scalar(
                select(Agent).where(
                    Agent.project_id == owner.id,
                    Agent.role == MANAGER,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )
            if manager is None:
                raise WorkError(f"project {owner.name} has no active manager to take the task")
            assignee = manager.id
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
