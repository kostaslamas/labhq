"""What the approvals page may know about an approval, and how a row becomes it."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Agent, Approval, Project, Task


class ProjectRef(BaseModel):
    id: int
    name: str


class TaskRef(BaseModel):
    id: int
    title: str


class AgentRef(BaseModel):
    id: int
    title: str
    role: str


class ApprovalOut(BaseModel):
    id: int
    type: str
    risk_class: RiskClass
    status: ApprovalStatus
    # What will run if approved: the stored request, as the executor will read it.
    payload: dict[str, Any]
    project: ProjectRef | None
    task: TaskRef | None
    requester: AgentRef | None
    branch: str | None
    remote: str | None
    created_at: datetime
    # Who or what settled it and how, as stored; absent while the approval is pending.
    decided_by: str | None
    decided_at: datetime | None
    confirmation_kind: str | None
    decision_note: str | None
    executed_at: datetime | None
    execution: dict[str, Any] | None


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    # The passkey assertion from the step-up prompt; required to approve a heavy action.
    credential: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


def text_of(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


async def describe(db: AsyncSession, approval: Approval) -> ApprovalOut:
    task = await db.get(Task, approval.task_id) if approval.task_id is not None else None
    project_id = task.project_id if task is not None else None
    project = await db.get(Project, project_id) if project_id is not None else None
    agent_id = approval.requested_by_agent_id
    agent = await db.get(Agent, agent_id) if agent_id is not None else None
    return ApprovalOut(
        id=approval.id,
        type=approval.type,
        risk_class=approval.risk_class,
        status=approval.status,
        payload=approval.payload,
        project=ProjectRef(id=project.id, name=project.name) if project else None,
        task=TaskRef(id=task.id, title=task.title) if task else None,
        requester=AgentRef(id=agent.id, title=agent.title, role=agent.role) if agent else None,
        branch=text_of(approval.payload, "branch"),
        remote=text_of(approval.payload, "url"),
        created_at=approval.created_at,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        confirmation_kind=approval.confirmation_kind,
        decision_note=approval.decision_note,
        executed_at=approval.executed_at,
        execution=approval.execution,
    )
