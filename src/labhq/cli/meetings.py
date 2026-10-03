"""`labhq meetings start|list|show`: request a meeting, list them, read one's minutes."""

from collections.abc import Awaitable
from typing import Annotated

import typer
from sqlalchemy import select

from labhq.approvals import ApprovalService
from labhq.callcenter.answers.minutes import meeting_ref
from labhq.cli.context import CliError, Context, execute, fail
from labhq.db.enums import MeetingStatus
from labhq.db.models import Meeting, Project
from labhq.meetings import (
    MeetingError,
    MeetingNotFoundError,
    MeetingRunner,
    MeetingService,
    MinutesView,
    read_minutes,
)
from labhq.money import format_micros
from labhq.runs import RunService
from labhq.work import find_project

meetings_app = typer.Typer(help="Meetings: request, list, show.", no_args_is_help=True)

LIST_LIMIT = 20


def _service(context: Context) -> MeetingService:
    approvals = ApprovalService(context.sessions, clock=context.clock)
    # Turns run each agent through its own adapter, outside any task checkout.
    runner = MeetingRunner(
        context.sessions,
        clock=context.clock,
        runs=RunService(context.sessions, clock=context.clock),
    )
    return MeetingService(context.sessions, clock=context.clock, approvals=approvals, runner=runner)


async def _guarded(meeting: Awaitable[Meeting]) -> Meeting:
    try:
        return await meeting
    except MeetingError as error:
        raise CliError(str(error)) from error


def _request(project: str, kind: str, agenda: str | None, participants: list[int] | None) -> None:
    async def body(context: Context) -> Meeting:
        async with context.sessions() as db:
            project_id = (await find_project(db, project)).id
        return await _guarded(
            _service(context).request(
                project_id=project_id, kind=kind, agenda=agenda, participants=participants
            )
        )

    meeting = execute(body)
    typer.echo(
        f"meeting {meeting.id} requested: {meeting.kind} [{meeting.status}]; "
        f"approve it with `labhq approvals approve {meeting.approval_id}`, then run it with "
        f"`labhq meetings start --meeting {meeting.id}`"
    )


def _run(meeting_id: int) -> None:
    async def body(context: Context) -> Meeting:
        return await _guarded(_service(context).start(meeting_id))

    meeting = execute(body)
    reason = f" ({meeting.end_reason})" if meeting.end_reason else ""
    typer.echo(f"meeting {meeting.id}: {meeting.kind} [{meeting.status}]{reason}")
    if meeting.status is MeetingStatus.FAILED:
        fail(f"meeting {meeting.id} failed{reason}")


@meetings_app.command("start")
def start(
    project: Annotated[
        str | None, typer.Argument(help="Project name or id to request a meeting for.")
    ] = None,
    meeting: Annotated[
        int | None,
        typer.Option(help="Run this requested meeting now; its approval must be decided."),
    ] = None,
    kind: Annotated[str, typer.Option(help="Meeting kind: standup, planning or review.")] = (
        "standup"
    ),
    agenda: Annotated[
        str | None, typer.Option(help="What to discuss. Default: the kind's agenda.")
    ] = None,
    participant: Annotated[
        list[int] | None,
        typer.Option(help="An attending agent id; repeat it. Default: the kind's roles."),
    ] = None,
) -> None:
    """Request a meeting for PROJECT, or run an approved one with --meeting."""
    if project is not None and meeting is None:
        _request(project, kind, agenda, participant)
    elif meeting is not None and project is None:
        _run(meeting)
    else:
        fail("give a project to request a meeting, or --meeting to run an approved one")


@meetings_app.command("list")
def list_command(
    project: Annotated[str | None, typer.Option(help="Only this project, by name or id.")] = None,
    kind: Annotated[str | None, typer.Option(help="Only meetings of this kind.")] = None,
    status: Annotated[MeetingStatus | None, typer.Option(help="Only this status.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="At most this many, newest first.")] = (
        LIST_LIMIT
    ),
) -> None:
    """List meetings, newest first."""

    async def body(context: Context) -> list[str]:
        async with context.sessions() as db:
            query = select(Meeting, Project.name).join(Project, Project.id == Meeting.project_id)
            if project is not None:
                query = query.where(Meeting.project_id == (await find_project(db, project)).id)
            if kind is not None:
                query = query.where(Meeting.kind == kind)
            if status is not None:
                query = query.where(Meeting.status == status)
            rows = await db.execute(
                query.order_by(Meeting.created_at.desc(), Meeting.id.desc()).limit(limit)
            )
            return [
                f"meeting {meeting.id} ({meeting_ref(meeting.id)}): {meeting.kind} for {name} "
                f"[{meeting.status}], requested {meeting.created_at.isoformat()}"
                for meeting, name in rows.all()
            ]

    lines = execute(body)
    typer.echo("\n".join(lines) if lines else "no meetings")


def minutes_lines(view: MinutesView, project: str) -> list[str]:
    """The transcript, decisions and action items of a meeting, for the terminal."""
    ended = f", {view.end_reason}" if view.end_reason else ""
    lines = [
        f"meeting {view.meeting_id}: {view.kind} for {project} [{view.status}{ended}]",
        f"agenda: {view.agenda}",
        f"participants: {', '.join(p.display_name for p in view.participants) or '-'}",
        f"cost: {format_micros(view.cost_micros)} ({view.cost_micros} micros)",
        "transcript:",
        *(f"  [{entry.speaker}] {entry.text}" for entry in view.transcript),
        "decisions:",
        *(f"  {decision.position}. {decision.text}" for decision in view.decisions),
        "action items:",
        *(
            f"  - {item.text} -> agent {item.assignee_agent_id or '-'}, "
            f"task {item.task_id} [{item.task_status}]"
            for item in view.action_items
        ),
    ]
    return lines


@meetings_app.command("show")
def show(meeting_id: Annotated[int, typer.Argument(help="The meeting's id.")]) -> None:
    """Show a meeting's transcript, decisions and action items."""

    async def body(context: Context) -> list[str]:
        async with context.sessions() as db:
            try:
                view = await read_minutes(db, meeting_id)
            except MeetingNotFoundError as error:
                raise CliError(str(error)) from error
            project = await db.get_one(Project, view.project_id)
            return minutes_lines(view, project.name)

    typer.echo("\n".join(execute(body)))
