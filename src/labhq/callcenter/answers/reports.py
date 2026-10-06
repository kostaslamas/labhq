"""`reports`: what workers and their supervisors last reported, per project and per agent.

Status questions are answered from what agents wrote down: task reports and handoffs, review
results (a manager's report to the CEO is its report on a root task) and status files, with
each agent's last run. Every line names the reporter and the report's age. Nothing here
wakes the CEO or any agent.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.phrasing import clean
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, DepartmentStatus, ProjectStatus
from labhq.db.models import Agent, Comment, Department, Project, Run, StatusUpdate, Task
from labhq.departments import find_department
from labhq.speech import join_sentences, say_ago, speakable
from labhq.work import WorkError, find_project

AGENTS_PER_PROJECT = 4
REPORT_WORDS = 25
SCANNED = 200
SUMMARY_FIELD = "summary"


@dataclass(frozen=True)
class Report:
    agent: Agent
    at: datetime
    # "reported" from the task's assignee, "reviewed" from its supervisor.
    verb: str
    text: str
    task: Task | None


def _reporter(agent: Agent) -> str:
    if " ".join(agent.title.split()).casefold() == agent.role.casefold():
        return clean(agent.title)
    return f"{clean(agent.title)}, the {clean(agent.role)}"


type Scope = tuple[ColumnElement[bool], ColumnElement[bool]]


def _of_project(project_id: int) -> Scope:
    return Task.project_id == project_id, Agent.project_id == project_id


def _of_department(department_id: int) -> Scope:
    return Task.department_id == department_id, Agent.department_id == department_id


async def _comment_reports(db: AsyncSession, tasks_in: ColumnElement[bool]) -> list[Report]:
    rows = await db.execute(
        select(Comment, Task, Agent)
        .join(Task, Task.id == Comment.task_id)
        .join(Agent, Agent.id == Comment.author_agent_id)
        .where(tasks_in)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(SCANNED)
    )
    return [
        Report(
            agent,
            comment.created_at,
            "reported" if task.assignee_id == agent.id else "reviewed",
            comment.body,
            task,
        )
        for comment, task, agent in rows.all()
    ]


async def _status_reports(db: AsyncSession, agents_in: ColumnElement[bool]) -> list[Report]:
    rows = await db.execute(
        select(StatusUpdate, Agent)
        .join(Agent, Agent.id == StatusUpdate.agent_id)
        .where(agents_in)
        .order_by(StatusUpdate.observed_at.desc(), StatusUpdate.id.desc())
        .limit(SCANNED)
    )
    reports = []
    for update, agent in rows.all():
        summary = update.fields.get(SUMMARY_FIELD)
        if isinstance(summary, str) and summary.strip():
            task = await db.get(Task, update.task_id) if update.task_id is not None else None
            reports.append(Report(agent, update.observed_at, "wrote in its status", summary, task))
    return reports


async def _last_run(db: AsyncSession, agent_id: int) -> Run | None:
    return await db.scalar(
        select(Run).where(Run.agent_id == agent_id).order_by(Run.id.desc()).limit(1)
    )


async def _say_report(db: AsyncSession, clock: Clock, report: Report) -> list[str]:
    on_task = f" on T{report.task.id}, {clean(report.task.title)}" if report.task else ""
    parts = [
        f"{_reporter(report.agent)} {report.verb}{on_task}, {say_ago(clock.now() - report.at)}",
        f"It said: {clean(report.text, REPORT_WORDS)}",
    ]
    if report.task is not None:
        parts.append(f"The task is {report.task.status.value.replace('_', ' ')}")
    run = await _last_run(db, report.agent.id)
    if run is not None:
        moment = run.finished_at or run.started_at or run.created_at
        status = run.status.value.replace("_", " ")
        parts.append(f"Its last run is {status}, from {say_ago(clock.now() - moment)}")
        if run.created_at > report.at:
            parts.append("It has run since this report, so the report may be stale")
    return parts


async def _scope_reports(db: AsyncSession, clock: Clock, label: str, scope: Scope) -> list[str]:
    tasks_in, agents_in = scope
    found = await _comment_reports(db, tasks_in) + await _status_reports(db, agents_in)
    latest: dict[int, Report] = {}
    for report in sorted(found, key=lambda report: report.at, reverse=True):
        if report.agent.status is not AgentStatus.RETIRED:
            latest.setdefault(report.agent.id, report)
    if not latest:
        return [f"In {clean(label)}, nobody has reported yet"]
    parts = [f"Reports in {clean(label)}"]
    for report in list(latest.values())[:AGENTS_PER_PROJECT]:
        parts += await _say_report(db, clock, report)
    if len(latest) > AGENTS_PER_PROJECT:
        parts.append(f"{len(latest) - AGENTS_PER_PROJECT} more agents have reported")
    return parts


async def _named(db: AsyncSession, reference: str) -> tuple[str, Scope]:
    """The project, or else the department, a caller named."""
    try:
        project = await find_project(db, reference)
    except WorkError:
        department = await find_department(db, reference)
        return department.name, _of_department(department.id)
    return project.name, _of_project(project.id)


async def reports(db: AsyncSession, clock: Clock, project: str | None = None) -> str:
    """The latest report of each agent, per project and department, or for the one named."""
    scopes: list[tuple[str, Scope]] = []
    if project:
        try:
            scopes = [await _named(db, project)]
        except WorkError as error:
            return speakable(f"I could not find that project. {error}.")
    else:
        for each in await db.scalars(
            select(Project).where(Project.status == ProjectStatus.ACTIVE).order_by(Project.name)
        ):
            scopes.append((each.name, _of_project(each.id)))
        for unit in await db.scalars(
            select(Department)
            .where(Department.status == DepartmentStatus.ACTIVE)
            .order_by(Department.name)
        ):
            scopes.append((unit.name, _of_department(unit.id)))
    if not scopes:
        return speakable("There are no projects yet.")
    parts: list[str] = []
    for label, scope in scopes:
        parts += await _scope_reports(db, clock, label, scope)
    return speakable(join_sentences(parts))
