"""The queries behind Today. Pending work reuses the call center's, so voice and page agree."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.api.today.schemas import (
    BudgetNotice,
    ExecutedApproval,
    NeedsYou,
    OpenIncident,
    PendingApproval,
    PendingQuestion,
    SpendWithoutOutput,
    TodayDeliverable,
)
from labhq.budgets.periods import period_start
from labhq.budgets.settings import get_budget_settings
from labhq.callcenter.answers.pending import count_pending, open_questions, pending_approvals
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus, BudgetScope, IncidentStatus, RiskClass, TaskStatus
from labhq.db.models import (
    Agent,
    Approval,
    BudgetWarning,
    CostEvent,
    HealthRule,
    Host,
    Incident,
    Project,
    Run,
    Task,
)

PUBLISHING_ACTIONS = ("push", "merge")
type ProjectRef = tuple[int | None, str | None]
NO_PROJECT: ProjectRef = (None, None)


async def deliverables(db: AsyncSession, since: datetime) -> list[TodayDeliverable]:
    rows = (
        await db.execute(
            select(Task, Project.name)
            .join(Project, Project.id == Task.project_id)
            .where(Task.status == TaskStatus.DONE, Task.updated_at >= since)
            .order_by(Task.updated_at.desc(), Task.id)
        )
    ).all()
    ids = [task.id for task, _ in rows]
    published = await _published(db, ids)
    costs = await _task_costs(db, ids)
    result: list[TodayDeliverable] = []
    for task, project_name in rows:
        approvals = published.get(task.id, [])
        branches = [item.branch for item in approvals if item.branch]
        result.append(
            TodayDeliverable(
                task_id=task.id,
                title=task.title,
                project_id=task.project_id,
                project_name=project_name,
                finished_at=task.updated_at,
                branch=branches[0] if branches else None,
                commit_count=len({item.commit for item in approvals if item.commit}),
                approvals=approvals,
                cost_micros=costs.get(task.id, 0),
            )
        )
    return result


async def _published(db: AsyncSession, task_ids: list[int]) -> dict[int, list[ExecutedApproval]]:
    if not task_ids:
        return {}
    rows = await db.scalars(
        select(Approval)
        .where(
            Approval.task_id.in_(task_ids),
            Approval.type.in_(PUBLISHING_ACTIONS),
            Approval.status == ApprovalStatus.EXECUTED,
        )
        .order_by(Approval.executed_at.desc(), Approval.id)
    )
    found: dict[int, list[ExecutedApproval]] = {}
    for approval in rows:
        if approval.task_id is None:
            continue
        found.setdefault(approval.task_id, []).append(
            ExecutedApproval(
                id=approval.id,
                type=approval.type,
                status=approval.status,
                branch=_text(approval.payload.get("branch")),
                commit=_text(approval.payload.get("commit")),
            )
        )
    return found


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


async def _task_costs(db: AsyncSession, task_ids: list[int]) -> dict[int, int]:
    if not task_ids:
        return {}
    rows = await db.execute(
        select(Run.task_id, func.sum(CostEvent.cost_micros))
        .join(Run, Run.id == CostEvent.run_id)
        .where(Run.task_id.in_(task_ids))
        .group_by(Run.task_id)
    )
    return {task_id: int(total) for task_id, total in rows.all() if task_id is not None}


async def needs_you(db: AsyncSession, clock: Clock) -> NeedsYou:
    approvals_total, questions_total = await count_pending(db)
    approvals = await _approvals(db, approvals_total)
    questions = await _questions(db, questions_total)
    incidents = await _incidents(db)
    warnings = await _budget_warnings(db, clock)
    return NeedsYou(
        count=len(approvals) + len(questions) + len(incidents) + len(warnings),
        approvals=approvals,
        questions=questions,
        incidents=incidents,
        budget_warnings=warnings,
    )


async def _projects_of(db: AsyncSession, task_ids: set[int]) -> dict[int, ProjectRef]:
    if not task_ids:
        return {}
    rows = await db.execute(
        select(Task.id, Project.id, Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(Task.id.in_(task_ids))
    )
    return {task_id: (project_id, name) for task_id, project_id, name in rows.all()}


async def _approvals(db: AsyncSession, total: int) -> list[PendingApproval]:
    rows = await pending_approvals(db, max(total, 1))
    projects = await _projects_of(db, {a.task_id for a, _ in rows if a.task_id is not None})
    items = [
        PendingApproval(
            id=approval.id,
            type=approval.type,
            risk_class=approval.risk_class,
            status=approval.status,
            created_at=approval.created_at,
            task_id=approval.task_id,
            task_title=title,
            project_id=projects.get(approval.task_id or 0, NO_PROJECT)[0],
            project_name=projects.get(approval.task_id or 0, NO_PROJECT)[1],
        )
        for approval, title in rows
    ]
    # Stable: equal risk keeps the call center's oldest-first order.
    return sorted(items, key=lambda item: item.risk_class is not RiskClass.HEAVY)


async def _questions(db: AsyncSession, total: int) -> list[PendingQuestion]:
    rows = await open_questions(db, max(total, 1))
    projects = await _projects_of(db, {q.task_id for q, _ in rows if q.task_id is not None})
    return [
        PendingQuestion(
            id=question.id,
            status=question.status,
            question=question.question,
            agent_title=agent_title,
            task_id=question.task_id,
            project_id=projects.get(question.task_id or 0, NO_PROJECT)[0],
            created_at=question.created_at,
        )
        for question, agent_title in rows
    ]


async def _incidents(db: AsyncSession) -> list[OpenIncident]:
    rows = await db.execute(
        select(Incident, HealthRule.name, Host.name)
        .join(HealthRule, HealthRule.id == Incident.rule_id)
        .join(Host, Host.id == Incident.host_id)
        .where(Incident.status == IncidentStatus.OPEN)
        .order_by(Incident.opened_at, Incident.id)
    )
    return [
        OpenIncident(
            id=incident.id,
            status=incident.status,
            rule_name=rule,
            host_name=host,
            opened_at=incident.opened_at,
        )
        for incident, rule, host in rows.all()
    ]


async def _budget_warnings(db: AsyncSession, clock: Clock) -> list[BudgetNotice]:
    start = period_start(get_budget_settings().period, clock.now())
    rows = await db.scalars(
        select(BudgetWarning)
        .where(BudgetWarning.period_start == start)
        .order_by(BudgetWarning.created_at, BudgetWarning.id)
    )
    warnings = list(rows)
    agent_ids = [w.scope_id for w in warnings if w.scope is BudgetScope.AGENT]
    project_ids = [w.scope_id for w in warnings if w.scope is BudgetScope.PROJECT]
    agents = {
        key: title
        for key, title in await db.execute(
            select(Agent.id, Agent.title).where(Agent.id.in_(agent_ids))
        )
    }
    projects = {
        key: name
        for key, name in await db.execute(
            select(Project.id, Project.name).where(Project.id.in_(project_ids))
        )
    }
    names = {BudgetScope.AGENT: agents, BudgetScope.PROJECT: projects}
    return [
        BudgetNotice(
            id=warning.id,
            scope=warning.scope,
            scope_id=warning.scope_id,
            name=names[warning.scope].get(warning.scope_id, f"#{warning.scope_id}"),
            spent_micros=warning.spent_micros,
            budget_micros=warning.budget_micros,
            created_at=warning.created_at,
        )
        for warning in warnings
    ]


async def spend_without_output(
    db: AsyncSession, since: datetime, delivered: list[TodayDeliverable]
) -> list[SpendWithoutOutput]:
    """Agents that cost money in the window while none of their runs reached a deliverable."""
    delivered_agents = set(
        await db.scalars(
            select(Run.agent_id)
            .where(Run.task_id.in_([item.task_id for item in delivered]))
            .distinct()
        )
    )
    total = func.sum(CostEvent.cost_micros)
    rows = await db.execute(
        select(Agent.id, Agent.title, Project.id, Project.name, total)
        .join(Agent, Agent.id == CostEvent.agent_id)
        .outerjoin(Project, Project.id == Agent.project_id)
        .where(CostEvent.created_at >= since)
        .group_by(Agent.id, Agent.title, Project.id, Project.name)
        .order_by(total.desc(), Agent.id)
    )
    return [
        SpendWithoutOutput(
            agent_id=agent_id,
            agent_title=title,
            project_id=project_id,
            project_name=project_name,
            cost_micros=int(spent),
        )
        for agent_id, title, project_id, project_name, spent in rows.all()
        if agent_id not in delivered_agents and int(spent) > 0
    ]
