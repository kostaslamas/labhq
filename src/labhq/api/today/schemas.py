"""The Today response. Costs are integer micro-USD (ADR 0002); nothing here lists live work."""

from datetime import datetime

from pydantic import BaseModel

from labhq.db.enums import ApprovalStatus, BudgetScope, IncidentStatus, QuestionStatus, RiskClass


class ExecutedApproval(BaseModel):
    id: int
    # The action type, a registry key such as `push` or `merge`.
    type: str
    status: ApprovalStatus
    branch: str | None
    commit: str | None


class TodayDeliverable(BaseModel):
    task_id: int
    title: str
    project_id: int
    project_name: str
    finished_at: datetime
    # The task branch the push or merge approvals published; None when nothing was published.
    branch: str | None
    # Distinct commits that executed pushes and merges published for the task.
    commit_count: int
    approvals: list[ExecutedApproval]
    cost_micros: int


class PendingApproval(BaseModel):
    id: int
    type: str
    risk_class: RiskClass
    status: ApprovalStatus
    created_at: datetime
    task_id: int | None
    task_title: str | None
    project_id: int | None
    project_name: str | None


class PendingQuestion(BaseModel):
    id: int
    status: QuestionStatus
    question: str
    agent_title: str
    task_id: int | None
    project_id: int | None
    created_at: datetime


class OpenIncident(BaseModel):
    id: int
    status: IncidentStatus
    rule_name: str
    host_name: str
    opened_at: datetime


class BudgetNotice(BaseModel):
    """A budget that crossed its warning line in the current period."""

    id: int
    scope: BudgetScope
    scope_id: int
    name: str
    spent_micros: int
    budget_micros: int
    created_at: datetime


class NeedsYou(BaseModel):
    count: int
    # Heavy first, then oldest first.
    approvals: list[PendingApproval]
    questions: list[PendingQuestion]
    incidents: list[OpenIncident]
    budget_warnings: list[BudgetNotice]


class SpendWithoutOutput(BaseModel):
    agent_id: int
    agent_title: str
    project_id: int | None
    project_name: str | None
    cost_micros: int


class Today(BaseModel):
    since: datetime
    until: datetime
    deliverables: list[TodayDeliverable]
    needs_you: NeedsYou
    spend_without_output: list[SpendWithoutOutput]
