"""`labhq onboard`: one command from an empty data directory to a working, verified system."""

import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import typer

from labhq.cli.context import fail, load_settings, make_clock
from labhq.cli.serve import serve
from labhq.onboard import (
    OnboardContext,
    OnboardError,
    OnboardSettings,
    StepReport,
    default_steps,
    describe,
    detect_platform,
    render_qr,
    run_steps,
)
from labhq.onboard.probes import report as probe_report

READY = "labhq is ready."
# The MCP library switches the whole process to INFO logging, and httpx then logs every request
# URL, the connector secret included.
QUIET_LOGGERS = ("httpx", "mcp")


@contextmanager
def _quiet() -> Iterator[None]:
    loggers = [logging.getLogger(name) for name in QUIET_LOGGERS]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)


def _ask(question: str, default: str) -> str:
    # An empty default would make typer repeat the question; show it as "skip" instead.
    answer: str = typer.prompt(question, default=default, show_default=bool(default))
    return answer


def _summary(reports: list[StepReport]) -> None:
    for step in reports:
        outcome = step.outcome
        if outcome is None or outcome.link is None:
            continue
        typer.echo(f"\n{outcome.label or step.name}: {outcome.link}")
        if outcome.qr:
            typer.echo(render_qr(outcome.link))
    for step in reports:
        if step.later is not None:
            typer.echo(f"\nLater, {step.name}:")
            for line in describe(step.later):
                typer.echo(f"  {line}")


def onboard(
    offer: Annotated[
        list[str] | None,
        typer.Argument(help="Optional steps to set up too, such as `discord`.", show_default=False),
    ] = None,
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="Never prompt; for CI and scripts.")
    ] = False,
    no_serve: Annotated[
        bool, typer.Option("--no-serve", help="Stop after the checks instead of serving.")
    ] = False,
    port: Annotated[int | None, typer.Option(help="Local port for the MCP server.")] = None,
) -> None:
    """Set labhq up, check it end to end, then serve it in the foreground."""
    unknown = sorted(set(offer or ()) - {step.name for step in default_steps})
    if unknown:
        fail(f"no onboarding step named {', '.join(unknown)}")
    settings = load_settings()
    onboarding = OnboardSettings()
    if port is not None:
        onboarding = onboarding.model_copy(update={"port": port})
    context = OnboardContext(
        settings=settings,
        onboard=onboarding,
        clock=make_clock(),
        platform=detect_platform(),
        environ=os.environ,
        which=shutil.which,
        say=typer.echo,
        confirm=None if non_interactive else (lambda prompt: typer.confirm(prompt)),
        ask=None if non_interactive else _ask,
        offered=frozenset(offer or ()),
    )
    with context.resources:
        typer.echo(f"Onboarding labhq in {settings.data_dir}")
        typer.echo(f"Found: {probe_report(context)}")
        try:
            with _quiet():
                reports = run_steps(default_steps, context)
        except OnboardError as error:
            fail(str(error))
        _summary(reports)
        typer.echo(f"\n{READY}")
        if no_serve:
            return
        # The tunnel stays open and keeps its URL; the full program takes over the port.
        if context.server is not None:
            context.server.stop()
        serve(host=onboarding.host, port=onboarding.port)
