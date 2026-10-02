"""The `labhq` command. Foundation ships `--version`; the CLI issue adds the commands."""

from typing import Annotated

import typer

from labhq import __version__

app = typer.Typer(name="labhq", help="Self-hosted project orchestrator.", no_args_is_help=True)


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
