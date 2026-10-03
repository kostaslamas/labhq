"""The `labhq` command: set up, add work, run the scheduler, decide approvals, check health."""

from typing import Annotated

import typer

import labhq.roles  # noqa: F401  (registers the role instructions and tools)
from labhq import __version__
from labhq.cli.adopt import adopt_app
from labhq.cli.approvals import approvals_app
from labhq.cli.demo import demo
from labhq.cli.health import health
from labhq.cli.hosts import hosts_app
from labhq.cli.mcp import mcp_app
from labhq.cli.meetings import meetings_app
from labhq.cli.notify import notify_app
from labhq.cli.onboard import onboard
from labhq.cli.org import org_app
from labhq.cli.passkey import passkey_app
from labhq.cli.ready import ready
from labhq.cli.rules import rules_app
from labhq.cli.running import run
from labhq.cli.serve import serve
from labhq.cli.work import agent_app, init, project_app, task_app
from labhq.it.cli import it_app

app = typer.Typer(name="labhq", help="Self-hosted project orchestrator.", no_args_is_help=True)

app.command()(init)
app.add_typer(project_app, name="project")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.command()(run)
app.add_typer(approvals_app, name="approvals")
app.command()(health)
app.add_typer(hosts_app, name="hosts")
app.add_typer(mcp_app, name="mcp")
app.add_typer(notify_app, name="notify")
app.add_typer(org_app, name="org")
app.add_typer(passkey_app, name="passkey")
app.add_typer(rules_app, name="rules")
app.add_typer(meetings_app, name="meetings")
app.add_typer(it_app, name="it")
app.command()(demo)
app.command()(serve)
app.command()(onboard)
app.command()(ready)
app.add_typer(adopt_app, name="adopt")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"labhq {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Run projects with a team of AI agents."""
