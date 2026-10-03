"""`labhq it start|wake`: create the IT agent, and run one pass of its wake-ups by hand."""

from typing import Annotated

import typer

from labhq.cli.context import Context, execute
from labhq.cli.engine import cli_adapters
from labhq.db.models import Agent
from labhq.it.agent import ensure_it_agent
from labhq.it.department import ItDepartment, ItPass

it_app = typer.Typer(help="The IT agent that watches the machines.", no_args_is_help=True)


@it_app.command("start")
def start(
    adapter: Annotated[
        str | None, typer.Option(help="The IT agent's adapter. Default: the org_adapter setting.")
    ] = None,
) -> None:
    """Show the IT agent, creating it (and the CEO it reports to) on first use."""

    async def body(context: Context) -> Agent:
        return await ensure_it_agent(
            context.sessions,
            context.clock,
            adapters=cli_adapters().adapter_keys(),
            adapter=adapter,
        )

    agent = execute(body)
    typer.echo(
        f"agent {agent.id} {agent.title} ({agent.role}, {agent.adapter}, read-only): {agent.status}"
    )


@it_app.command("wake")
def wake() -> None:
    """Queue what the IT agent is due now: new tickets and the daily report."""

    async def body(context: Context) -> ItPass:
        return await ItDepartment(context.sessions, context.clock).tick()

    result = execute(body)
    if result.agent_id is None:
        typer.echo("no IT agent; create one with `labhq it start`")
        return
    lines = [f"wakeup {item.request.id}: {item.outcome}" for item in result.incidents]
    if result.report is not None:
        lines.append(f"report wakeup {result.report.request.id}: {result.report.outcome}")
    typer.echo("\n".join(lines) if lines else "nothing due")
