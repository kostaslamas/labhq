"""Response models of `/api/projects`. Every amount is integer micro-USD (ADR 0002)."""

from datetime import datetime

from pydantic import BaseModel, Field

from labhq.budgets import Decision
from labhq.db.enums import AgentStatus, ProjectStatus, TaskStatus


class Budget(BaseModel):
    """One budget level as `labhq.budgets` reads it, for the current period."""

    budget_micros: int | None = Field(description="The limit; absent means no limit.")
    spent_micros: int
    # `allow`, `warn` (80% by default) or `stop` (100%): the verdict of `labhq.budgets.decide`.
    state: Decision
    # Whole percent of the limit spent, rounded down; absent without a limit. Integer math on
    # the server, so the UI never divides money.
    used_percent: int | None


class TaskCount(BaseModel):
    status: TaskStatus
    count: int


class Deliverable(BaseModel):
    """A done task and what it produced."""

    task_id: int
    title: str
    branch: str
    # Full commit names pinned by executed push or merge approvals, oldest first.
    commits: list[str]
    cost_micros: int
    done_at: datetime


class SessionCounts(BaseModel):
    """Agent sessions in the project's folder, from the last scan."""

    total: int
    running: int
    waiting: int
    idle: int


class ProjectCard(BaseModel):
    id: int
    name: str
    status: ProjectStatus
    budget: Budget
    # Every open status, so a card lines up with its neighbours; closed tasks are not counted.
    open_tasks: list[TaskCount]
    latest_deliverable: Deliverable | None
    # None until a scan has run, or when it found no session in this folder.
    sessions: SessionCounts | None = None


class TeamMember(BaseModel):
    id: int
    role: str
    title: str
    adapter: str
    kind: str
    reports_to: int | None
    adopted: bool
    status: AgentStatus
    budget: Budget
    reports: list["TeamMember"]


class BudgetPolicy(BaseModel):
    warn_percent: int
    stop_percent: int
    period_start: datetime


class ProjectView(BaseModel):
    id: int
    name: str
    status: ProjectStatus
    budget: Budget
    policy: BudgetPolicy
    # Agents that report to nobody in this project, each with the subtree beneath.
    team: list[TeamMember]
    tasks: list[TaskCount]
    # The latest deliverables, newest first; `deliverables_total` counts all done tasks.
    deliverables: list[Deliverable]
    deliverables_total: int


class ProjectRef(BaseModel):
    project_id: int
