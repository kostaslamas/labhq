"""`reports`: what workers and their supervisors last reported, per project and per agent.

Status questions are answered from what agents wrote down: task reports and handoffs, review
results (a manager's report to the CEO is its report on a root task) and status files, with
each agent's last run. Every line names the reporter and the report's age. Nothing here
wakes the CEO or any agent.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.phrasing import clean
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, ProjectStatus
from labhq.db.models import Agent, Comment, Project, Run, StatusUpdate, Task
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


async def _comment_reports(db: AsyncSession, project_id: int) -> list[Report]:
    rows = await db.execute(
        select(Comment, Task, Agent)
        .join(Task, Task.id == Comment.task_id)
        .join(Agent, Agent.id == Comment.author_agent_id)
        .where(Task.project_id == project_id)
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


async def _status_reports(db: AsyncSession, project_id: int) -> list[Report]:
    rows = await db.execute(
        select(StatusUpdate, Agent)
        .join(Agent, Agent.id == StatusUpdate.agent_id)
        .where(Agent.project_id == project_id)
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


async def _project_reports(db: AsyncSession, clock: Clock, project: Project) -> list[str]:
    found = await _comment_reports(db, project.id) + await _status_reports(db, project.id)
    latest: dict[int, Report] = {}
    for report in sorted(found, key=lambda report: report.at, reverse=True):
        if report.agent.status is not AgentStatus.RETIRED:
            latest.setdefault(report.agent.id, report)
    if not latest:
        return [f"In {clean(project.name)}, nobody has reported yet"]
    parts = [f"Reports in {clean(project.name)}"]
    for report in list(latest.values())[:AGENTS_PER_PROJECT]:
        parts += await _say_report(db, clock, report)
    if len(latest) > AGENTS_PER_PROJECT:
        parts.append(f"{len(latest) - AGENTS_PER_PROJECT} more agents have reported")
    return parts


async def reports(db: AsyncSession, clock: Clock, project: str | None = None) -> str:
    """The latest report of each agent, per project, or for the one project named."""
    if project:
        try:
            projects = [await find_project(db, project)]
        except WorkError as error:
            return speakable(f"I could not find that project. {error}.")
    else:
        projects = list(
            await db.scalars(
                select(Project).where(Project.status == ProjectStatus.ACTIVE).order_by(Project.name)
            )
        )
    if not projects:
        return speakable("There are no projects yet.")
    parts: list[str] = []
    for each in projects:
        parts += await _project_reports(db, clock, each)
    return speakable(join_sentences(parts))
