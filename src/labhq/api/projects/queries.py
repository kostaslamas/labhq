"""Database reads for `/api/projects`. Spend and verdicts come from `labhq.budgets`."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.api.projects.schemas import Budget, Deliverable, TaskCount, TeamMember
from labhq.approvals.merge import MERGE_ACTION
from labhq.approvals.push import PUSH_ACTION
from labhq.budgets import BudgetSettings, decide, spent_micros
from labhq.db.enums import ApprovalStatus, TaskStatus
from labhq.db.models import Agent, Approval, CostEvent, Run, Task
from labhq.worktrees import branch_name

OPEN_STATUSES = tuple(
    status for status in TaskStatus if status not in (TaskStatus.DONE, TaskStatus.CANCELLED)
)
DELIVERABLE_LIMIT = 50
# Approvals whose payload pins the commit that left the machine.
_COMMIT_ACTIONS = (PUSH_ACTION, MERGE_ACTION)


async def budget_of(
    session: AsyncSession,
    scope_filter: ColumnElement[bool],
    limit_micros: int | None,
    since: datetime,
    settings: BudgetSettings,
) -> Budget:
    spent = await spent_micros(session, scope_filter, since)
    percent = None if not limit_micros else spent * 100 // limit_micros
    return Budget(
        budget_micros=limit_micros,
        spent_micros=spent,
        state=decide(spent, limit_micros, settings),
        used_percent=percent,
    )


async def task_counts(
    session: AsyncSession, project_ids: Sequence[int], statuses: Iterable[TaskStatus]
) -> dict[int, list[TaskCount]]:
    """Per project, one count for each of `statuses` (zero when there is none)."""
    wanted = tuple(statuses)
    rows = await session.execute(
        select(Task.project_id, Task.status, func.count())
        .where(Task.project_id.in_(project_ids), Task.status.in_(wanted))
        .group_by(Task.project_id, Task.status)
    )
    found = {(project_id, status): count for project_id, status, count in rows}
    return {
        project_id: [TaskCount(status=s, count=found.get((project_id, s), 0)) for s in wanted]
        for project_id in project_ids
    }


async def deliverables(
    session: AsyncSession, project_id: int, limit: int
) -> tuple[list[Deliverable], int]:
    """The latest done tasks of a project with their branch, commits and cost, and the total."""
    done = (Task.project_id == project_id, Task.status == TaskStatus.DONE)
    total = await session.scalar(select(func.count()).select_from(Task).where(*done)) or 0
    tasks = list(
        await session.scalars(
            select(Task).where(*done).order_by(Task.updated_at.desc(), Task.id.desc()).limit(limit)
        )
    )
    ids = [task.id for task in tasks]
    cost_rows = await session.execute(
        select(Run.task_id, func.sum(CostEvent.cost_micros))
        .join(Run, Run.id == CostEvent.run_id)
        .where(Run.task_id.in_(ids))
        .group_by(Run.task_id)
    )
    costs = {task_id: int(cost) for task_id, cost in cost_rows}
    commits: dict[int, list[str]] = {}
    approvals = await session.scalars(
        select(Approval)
        .where(
            Approval.task_id.in_(ids),
            Approval.type.in_(_COMMIT_ACTIONS),
            Approval.status == ApprovalStatus.EXECUTED,
        )
        .order_by(Approval.executed_at, Approval.id)
    )
    for approval in approvals:
        commit = approval.payload.get("commit")
        if approval.task_id is not None and isinstance(commit, str):
            known = commits.setdefault(approval.task_id, [])
            if commit not in known:
                known.append(commit)
    return [
        Deliverable(
            task_id=task.id,
            title=task.title,
            branch=branch_name(task.id, task.title),
            commits=commits.get(task.id, []),
            cost_micros=costs.get(task.id, 0),
            done_at=task.updated_at,
        )
        for task in tasks
    ], total


async def team_tree(
    session: AsyncSession, project_id: int, since: datetime, settings: BudgetSettings
) -> list[TeamMember]:
    """The agents of a project as a forest along `reports_to`."""
    agents = list(
        await session.scalars(
            select(Agent).where(Agent.project_id == project_id).order_by(Agent.id)
        )
    )
    members: dict[int, TeamMember] = {}
    for agent in agents:
        budget = await budget_of(
            session, CostEvent.agent_id == agent.id, agent.budget_micros, since, settings
        )
        members[agent.id] = TeamMember(
            id=agent.id,
            role=agent.role,
            title=agent.title,
            adapter=agent.adapter,
            status=agent.status,
            budget=budget,
            reports=[],
        )
    roots: list[TeamMember] = []
    for agent in agents:
        manager = members.get(agent.reports_to) if agent.reports_to is not None else None
        # A manager outside the project, or none, makes this agent a root.
        (manager.reports if manager is not None else roots).append(members[agent.id])
    reachable: set[int] = set()
    stack = [*roots]
    while stack:
        member = stack.pop()
        reachable.add(member.id)
        stack.extend(member.reports)
    # A reporting cycle has no root: list its members flat rather than hide them.
    for agent in agents:
        if agent.id not in reachable:
            members[agent.id].reports = []
            roots.append(members[agent.id])
    return roots
