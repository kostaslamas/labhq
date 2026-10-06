"""A voice order goes to the global CEO in the owner's words; a merge order asks for approval.

The CEO delegates down, so an order creates no task here: its words are stored as a request
of the current call and sent by request id, exactly as the Call Center sends them. A retry
with the same request id finds the stored request and sends nothing twice.

A merge order only requests the heavy `merge` approval: the owner approves it with a
passkey and the engine merges, never this call (plan §5, rule 7).
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.refs import approval_ref
from labhq.callcenter.calls.ceo import send_request
from labhq.callcenter.calls.tickets import current_call
from labhq.clock import Clock
from labhq.db.enums import CallRequestStatus
from labhq.db.models import CallRequest, Task
from labhq.speech import speakable
from labhq.work import WorkError, find_project, request_merge

# Kept apart from the Call Center's own `call-` tickets, so a caller key never names one.
REQUEST_PREFIX = "order-"
_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,58}")


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


async def _stored(db: AsyncSession, clock: Clock, request_id: str, text: str) -> CallRequest:
    request = await db.scalar(select(CallRequest).where(CallRequest.request_id == request_id))
    if request is not None:
        return request
    call, _ = await current_call(db, clock)
    now = clock.now()
    # The program sends this one itself; the Call Center agent must not pick it up.
    request = CallRequest(
        call_id=call.id,
        request_id=request_id,
        text=text,
        status=CallRequestStatus.ANSWERED,
        created_at=now,
        answered_at=now,
    )
    db.add(request)
    await db.flush()
    return request


async def order(
    db: AsyncSession,
    clock: Clock,
    *,
    text: str,
    request_id: str,
    project: str | None = None,
    merge: int | None = None,
) -> str:
    """Send `text` to the CEO as spoken, or with `merge` set to a task id, request its merge."""
    if merge is not None:
        if not project:
            return speakable("Say which project the task to merge is in.")
        return await _order_merge(db, clock, project, merge)
    if not text.strip():
        return speakable("I did not hear the order.")
    if not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must be 1 to 58 letters, digits or _ . : -")
    request = await _stored(db, clock, f"{REQUEST_PREFIX}{request_id}", text)
    return await send_request(db, clock, call_id=request.call_id, request_id=request.request_id)
