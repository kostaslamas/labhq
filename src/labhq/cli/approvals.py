"""`labhq approvals list|approve|reject`: the operator decides, the engine executes."""

import getpass
from typing import Annotated

import typer

from labhq.approvals import ApprovalService
from labhq.cli.context import Context, execute, fail
from labhq.cli.render import approval_line, execution_line
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval

# The operator at this terminal holds the machine already (approvals.policy).
CONFIRMATION = "cli"

approvals_app = typer.Typer(help="List and decide approvals.", no_args_is_help=True)


def decider() -> str:
    return f"cli:{getpass.getuser()}"


@approvals_app.command("list")
def list_approvals(
    status: Annotated[
        ApprovalStatus | None,
        typer.Option(help="Only approvals in this status. Default: pending."),
    ] = ApprovalStatus.PENDING,
    all_statuses: Annotated[
        bool, typer.Option("--all", help="Every approval, whatever its status.")
    ] = False,
) -> None:
    """List approvals, oldest first."""

    async def body(context: Context) -> list[Approval]:
        service = ApprovalService(context.sessions, clock=context.clock)
        return await service.list(None if all_statuses else status)

    approvals = execute(body)
    for approval in approvals:
        typer.echo(approval_line(approval))
    if not approvals:
        typer.echo("no approvals")


@approvals_app.command("approve")
def approve(
    approval_id: Annotated[int, typer.Argument(help="The approval's id.")],
    note: Annotated[str | None, typer.Option(help="Why, for the record.")] = None,
) -> None:
    """Approve a pending action; the engine then executes it (a push publishes the branch)."""

    async def body(context: Context) -> Approval:
        service = ApprovalService(context.sessions, clock=context.clock)
        return await service.approve(
            approval_id, decider=decider(), confirmation=CONFIRMATION, note=note
        )

    approval = execute(body)
    typer.echo(approval_line(approval))
    if approval.execution:
        typer.echo(execution_line(approval))
    if approval.status is ApprovalStatus.EXECUTION_FAILED:
        fail(f"approval {approval.id} was approved but its execution failed")


@approvals_app.command("reject")
def reject(
    approval_id: Annotated[int, typer.Argument(help="The approval's id.")],
    note: Annotated[str | None, typer.Option(help="Why, for the record.")] = None,
) -> None:
    """Reject a pending action; nothing is executed."""

    async def body(context: Context) -> Approval:
        service = ApprovalService(context.sessions, clock=context.clock)
        return await service.reject(
            approval_id, decider=decider(), confirmation=CONFIRMATION, note=note
        )

    typer.echo(approval_line(execute(body)))
