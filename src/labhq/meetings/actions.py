"""`decision_action`: a step a decision room agreed, executed only after the owner approved it.

The room's minutes create each task unassigned, so nothing is woken. The owner approves the
step as any light approval (a tap); only then does the executor assign the task. An agent's
own confirmation is refused (`owner_only`), so the CEO cannot act on a decision the owner
did not confirm.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals import ActionType, Executor, Payload, default_actions, default_executors
from labhq.db.enums import RiskClass
from labhq.db.models import Task
from labhq.hierarchy.executors import EngineAccess
from labhq.scheduler import enqueue
from labhq.work import WorkError
from labhq.work.service import assignment

DECISION_ACTION = "decision_action"


class DecisionActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    meeting_id: int
    item_id: int
    task_id: int
    assignee_id: int


def decision_executor(access: EngineAccess) -> Executor:
    def run(payload: Payload) -> dict[str, Any]:
        request = DecisionActionPayload.model_validate(payload)

        async def assign(db: AsyncSession) -> dict[str, Any]:
            task = await db.get(Task, request.task_id)
            if task is None:
                raise WorkError(f"no task {request.task_id}")
            if task.assignee_id is not None:
                raise WorkError(f"task {task.id} is already assigned")
            task.assignee_id = request.assignee_id
            task.updated_at = access.clock.now()
            reason = f"action item from decision meeting #{request.meeting_id}, confirmed"
            await enqueue(db, assignment(task, request.assignee_id, reason), access.clock)
            return {"task_id": task.id, "assignee_id": request.assignee_id}

        return access.run(assign)

    return Executor(run=run, validate=DecisionActionPayload.model_validate)


default_actions.register(
    DECISION_ACTION, ActionType(DECISION_ACTION, RiskClass.LIGHT, owner_only=True)
)
default_executors.register(DECISION_ACTION, decision_executor(EngineAccess()))
