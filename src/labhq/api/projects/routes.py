"""`GET /api/projects` and `GET /api/projects/{project_id}`."""

from fastapi import APIRouter
from sqlalchemy import select

from labhq.api.deps import ClockDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.pagination import Page, PageParamsDep, paginate
from labhq.api.projects.queries import (
    DELIVERABLE_LIMIT,
    OPEN_STATUSES,
    budget_of,
    deliverables,
    task_counts,
    team_tree,
)
from labhq.api.projects.schemas import BudgetPolicy, ProjectCard, ProjectView
from labhq.budgets import get_budget_settings, period_start
from labhq.db.enums import TaskStatus
from labhq.db.models import CostEvent, Project

NOT_FOUND_CODE = "project_not_found"

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def projects_list(
    session: SessionDep, clock: ClockDep, page: PageParamsDep
) -> Page[ProjectCard]:
    """One card per project: budget, open tasks by status and the latest deliverable."""
    settings = get_budget_settings()
    since = period_start(settings.period, clock.now())
    rows, cursor = await paginate(session, select(Project), (Project.name, Project.id), page)
    counts = await task_counts(session, [project.id for project in rows], OPEN_STATUSES)
    cards = []
    for project in rows:
        latest, _ = await deliverables(session, project.id, 1)
        cards.append(
            ProjectCard(
                id=project.id,
                name=project.name,
                status=project.status,
                budget=await budget_of(
                    session,
                    CostEvent.project_id == project.id,
                    project.budget_micros,
                    since,
                    settings,
                ),
                open_tasks=counts[project.id],
                latest_deliverable=latest[0] if latest else None,
            )
        )
    return Page(items=cards, next_cursor=cursor)


@router.get("/{project_id}")
async def projects_get(project_id: int, session: SessionDep, clock: ClockDep) -> ProjectView:
    """The project's team tree, deliverables, tasks by status and budget."""
    project = await session.get(Project, project_id)
    if project is None:
        raise ApiError(404, NOT_FOUND_CODE, "There is no project with that id.")
    settings = get_budget_settings()
    since = period_start(settings.period, clock.now())
    done, total = await deliverables(session, project.id, DELIVERABLE_LIMIT)
    return ProjectView(
        id=project.id,
        name=project.name,
        status=project.status,
        budget=await budget_of(
            session, CostEvent.project_id == project.id, project.budget_micros, since, settings
        ),
        policy=BudgetPolicy(
            warn_percent=settings.warn_percent,
            stop_percent=settings.stop_percent,
            period_start=since,
        ),
        team=await team_tree(session, project.id, since, settings),
        tasks=(await task_counts(session, [project.id], TaskStatus))[project.id],
        deliverables=done,
        deliverables_total=total,
    )
