"""`approvals list|approve|reject`: the operator decides, the engine executes."""

import getpass
from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.cli.runtime import CliError, run_with_database
from labhq.clock import SystemClock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval

# The operator at the terminal holds the machine already; see labhq.approvals.policy.
CLI_CONFIRMATION = "cli"
ALL_STATUSES = "all"

approvals_app = typer.Typer(help="List and decide approvals.", no_args_is_help=True)

IdArgument = Annotated[int, typer.Argument(help="Approval id, from `labhq approvals list`.")]
NoteOption = Annotated[str | None, typer.Option(help="Why, recorded with the decision.")]


def operator() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        # No login name in this environment; the decision is still recorded as the CLI's.
        return "cli-operator"


def describe(approval: Approval) -> str:
    payload = approval.payload
    target = f"{payload['branch']}@{str(payload['commit'])[:12]}" if "branch" in payload else ""
    task = f"task {approval.task_id}" if approval.task_id is not None else "no task"
    parts = [
        f"{approval.id}",
        approval.type,
        approval.risk_class,
        approval.status,
        task,
        approval.created_at.isoformat(timespec="seconds"),
        target,
    ]
    return "  ".join(part for part in parts if part)


def parse_status(value: str) -> ApprovalStatus | None:
    if value == ALL_STATUSES:
        return None
    try:
        return ApprovalStatus(value)
    except ValueError:
        known = ", ".join([*ApprovalStatus, ALL_STATUSES])
        raise CliError(f"unknown status {value!r}; use one of: {known}") from None


@approvals_app.command("list")
def approvals_list(
    status: Annotated[
        str, typer.Option(help="pending, approved, rejected, executed, ... or all.")
    ] = ApprovalStatus.PENDING.value,
) -> None:
    """List approvals, pending ones by default."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        wanted = parse_status(status)
        rows = await ApprovalService(sessions, clock=SystemClock()).list(wanted)
        if not rows:
            typer.echo(f"no {status} approvals")
        for approval in rows:
            typer.echo(describe(approval))

    run_with_database(job)


@approvals_app.command("approve")
def approvals_approve(approval_id: IdArgument, note: NoteOption = None) -> None:
    """Approve an action; the engine then executes it, e.g. pushes the branch."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        service = ApprovalService(sessions, clock=SystemClock())
        approval = await service.approve(
            approval_id, decider=operator(), confirmation=CLI_CONFIRMATION, note=note
        )
        typer.echo(describe(approval))
        if approval.status is ApprovalStatus.EXECUTION_FAILED:
            message = (approval.execution or {}).get("message", "unknown error")
            raise CliError(f"approval {approval.id} was approved but failed to execute: {message}")
        if approval.execution is not None:
            typer.echo(f"executed: {approval.execution}")

    run_with_database(job)


@approvals_app.command("reject")
def approvals_reject(approval_id: IdArgument, note: NoteOption = None) -> None:
    """Reject an action; nothing is executed."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        service = ApprovalService(sessions, clock=SystemClock())
        approval = await service.reject(
            approval_id, decider=operator(), confirmation=CLI_CONFIRMATION, note=note
        )
        typer.echo(describe(approval))

    run_with_database(job)
