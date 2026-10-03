"""The `labhq` command: set up, add work, run the scheduler, decide approvals, check health."""

from typing import Annotated

import typer

from labhq import __version__
from labhq.cli.approvals import approvals_app
from labhq.cli.demo import demo
from labhq.cli.health import health
from labhq.cli.running import run
from labhq.cli.work import agent_app, init, project_app, task_app

app = typer.Typer(name="labhq", help="Self-hosted project orchestrator.", no_args_is_help=True)

app.command()(init)
app.add_typer(project_app, name="project")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.command()(run)
app.add_typer(approvals_app, name="approvals")
app.command()(health)
app.command()(demo)


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
