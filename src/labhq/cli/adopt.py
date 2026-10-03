"""`labhq adopt discover|request|check`: take over an agent that already runs a project.

`request` only asks: the move happens when the owner approves the `adopt_agent` approval
with `labhq approvals approve`. `check` runs the engine checks on every adopted manager.
"""

import asyncio
from typing import Annotated

import typer

from labhq.adapters.tmux import TmuxError, default_kinds
from labhq.adoption import AdoptedChecks, AdoptionError, AdoptionRequest, Adoptions, discover
from labhq.adoption.checks import CheckReport
from labhq.adoption.move import default_server
from labhq.cli.context import CliError, Context, execute, fail
from labhq.cli.render import approval_line

adopt_app = typer.Typer(help="Adopt a running agent as a project's manager.", no_args_is_help=True)


@adopt_app.command("discover")
def discover_agents(
    kind: Annotated[str | None, typer.Option(help="Only agents of this CLI kind.")] = None,
) -> None:
    """List running agents of the known CLIs and their working directories."""
    if kind is not None and kind not in default_kinds.names():
        fail(f"no agent kind {kind!r}; known: {', '.join(default_kinds.names())}")
    found = [agent for agent in discover(default_kinds) if kind in (None, agent.kind)]
    for agent in found:
        typer.echo(f"pid {agent.pid} {agent.kind} in {agent.cwd}")
    if not found:
        typer.echo("no running agents of a known CLI")


@adopt_app.command("request")
def request(
    pid: Annotated[int, typer.Argument(help="Process id, from `labhq adopt discover`.")],
    project: Annotated[
        str | None,
        typer.Option(help="The project it will manage. Default: its repository's directory name."),
    ] = None,
) -> None:
    """Ask to adopt a running agent; nothing moves until the approval is approved."""

    async def body(context: Context) -> AdoptionRequest:
        try:
            return await Adoptions(context.sessions, clock=context.clock).request(
                pid, project=project
            )
        except AdoptionError as error:
            raise CliError(str(error)) from None

    adoption = execute(body)
    typer.echo(approval_line(adoption.approval))
    for warning in adoption.warnings:
        typer.echo(f"warning: {warning}", err=True)


def report_line(report: CheckReport) -> str:
    facts = {
        "turn ended": report.turn_ended,
        "status updated": report.status_updated,
        "status requested": report.status_requested,
        "rules sent": report.rules_sent,
        "checkout changed, owner notified": report.checkout_changed,
        "held by the plan cap": report.held,
    }
    seen = [name for name, value in facts.items() if value] or ["nothing new"]
    return f"agent {report.agent_id}: {', '.join(seen)}"


@adopt_app.command("check")
def check(
    every: Annotated[
        float | None, typer.Option(help="Repeat every this many seconds until interrupted.")
    ] = None,
) -> None:
    """Run the engine checks on every adopted manager."""

    async def body(context: Context) -> None:
        try:
            server = default_server()
        except TmuxError as error:
            raise CliError(str(error)) from None
        checks = AdoptedChecks(context.sessions, clock=context.clock, server=server)
        while True:
            for report in await checks.check_all():
                typer.echo(report_line(report))
            if every is None:
                return
            await asyncio.sleep(every)

    execute(body)
