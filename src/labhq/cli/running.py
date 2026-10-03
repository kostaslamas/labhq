"""`labhq run`: drive the scheduler once, or keep it running."""

from typing import Annotated

import typer

from labhq.cli.context import Context, execute, fail
from labhq.cli.engine import Engine, PassReport
from labhq.cli.render import approval_line, run_line


def print_report(report: PassReport) -> None:
    for run in report.runs:
        typer.echo(run_line(run))
    for approval in report.approvals:
        typer.echo(f"requested {approval_line(approval)}")
    if not report.runs:
        typer.echo("no runs finished")


def run(
    loop: Annotated[
        bool, typer.Option("--loop", help="Keep ticking until interrupted (Ctrl-C).")
    ] = False,
    max_ticks: Annotated[
        int | None, typer.Option(help="With --loop, stop after this many ticks.", min=1)
    ] = None,
) -> None:
    """Run the scheduler: start what may start, wait for it, request pushes for its work.

    Without --loop this is one pass: one tick, then it waits for the runs that tick
    started. It exits 1 when any of them did not succeed.
    """

    async def body(context: Context) -> PassReport:
        engine = Engine(context)
        if loop:
            return await engine.run_loop(max_ticks)
        return await engine.run_pass()

    try:
        report = execute(body)
    except KeyboardInterrupt:
        fail("interrupted; live runs were stopped and recorded as interrupted")
    print_report(report)
    if report.failed:
        fail(f"{len(report.failed)} run(s) did not succeed")
