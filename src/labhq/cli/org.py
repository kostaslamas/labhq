"""`labhq org ceo|assign-manager|propose-team|tree`: the CEO, its managers and their teams."""

import json
from typing import Annotated

import typer
from pydantic import TypeAdapter

from labhq.cli.context import Context, execute, fail
from labhq.cli.engine import cli_adapters
from labhq.cli.render import approval_line
from labhq.db.models import Agent
from labhq.hierarchy import Hierarchy, ManagerAssignment, Node, ProposedMember

org_app = typer.Typer(help="The CEO, project managers and their teams.", no_args_is_help=True)

MEMBERS = TypeAdapter(tuple[ProposedMember, ...])
INDENT = "  "


def hierarchy(context: Context) -> Hierarchy:
    return Hierarchy(context.sessions, clock=context.clock, adapters=cli_adapters().adapter_keys())


def agent_line(agent: Agent) -> str:
    project = f", project {agent.project_id}" if agent.project_id is not None else ""
    return (
        f"agent {agent.id} {agent.title} ({agent.role}, {agent.adapter}{project}): {agent.status}"
    )


def tree_lines(nodes: list[Node], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.append(f"{INDENT * depth}{agent_line(node.agent)}")
        lines.extend(tree_lines(node.reports, depth + 1))
    return lines


@org_app.command("ceo")
def ceo(
    adapter: Annotated[
        str | None, typer.Option(help="Adapter for a new CEO. Default: the org_adapter setting.")
    ] = None,
) -> None:
    """Show the CEO, creating it on first use."""

    async def body(context: Context) -> Agent:
        return await hierarchy(context).ensure_ceo(adapter)

    typer.echo(agent_line(execute(body)))


@org_app.command("assign-manager")
def assign_manager(
    project: Annotated[str, typer.Argument(help="Project id or name.")],
    adapter: Annotated[
        str | None, typer.Option(help="The manager's adapter. Default: the org_adapter setting.")
    ] = None,
    title: Annotated[str | None, typer.Option(help="The manager's title.")] = None,
) -> None:
    """Give a project without a manager its manager, reporting to the CEO."""

    async def body(context: Context) -> ManagerAssignment:
        return await hierarchy(context).assign_manager(project, adapter=adapter, title=title)

    assignment = execute(body)
    typer.echo(agent_line(assignment.manager))
    if assignment.approval is not None:
        typer.echo(approval_line(assignment.approval))


@org_app.command("propose-team")
def propose_team(
    manager: Annotated[int, typer.Argument(help="The proposing manager's agent id.")],
    members: Annotated[
        str,
        typer.Option(
            help=(
                "JSON list of members, each with key, role, title, adapter and optionally "
                "reports_to (another member's key; omitted reports to the manager)."
            )
        ),
    ],
) -> None:
    """Propose a team; nothing is created until a heavy `create_team` approval is approved."""
    try:
        proposed = MEMBERS.validate_python(json.loads(members))
    except ValueError as error:
        fail(f"--members is not a valid member list: {error}")

    async def body(context: Context) -> str:
        approval = await hierarchy(context).propose_team(manager, proposed)
        return approval_line(approval)

    typer.echo(execute(body))


@org_app.command("tree")
def tree() -> None:
    """Every agent that is not retired, under the agent it reports to."""

    async def body(context: Context) -> list[Node]:
        return await hierarchy(context).tree()

    lines = tree_lines(execute(body))
    typer.echo("\n".join(lines) if lines else "no agents")
