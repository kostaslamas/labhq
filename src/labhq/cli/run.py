"""`labhq run`: one scheduler pass, or a loop until interrupted."""

from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry
from labhq.adapters import default_registry as builtin_adapters
from labhq.approvals import ApprovalService
from labhq.cli.engine import Engine, Pass, TaskRunService
from labhq.cli.runtime import run_with_database, settings
from labhq.clock import Clock, SystemClock
from labhq.scheduler import Scheduler, get_scheduler_settings
from labhq.settings import Settings
from labhq.worktrees import default_root


def build_engine(
    sessions: async_sessionmaker[AsyncSession],
    config: Settings,
    clock: Clock,
    registry: AdapterRegistry = builtin_adapters,
) -> Engine:
    root = default_root(config)
    runs = TaskRunService(sessions, clock=clock, worktree_root=root, registry=registry)
    return Engine(
        sessions=sessions,
        scheduler=Scheduler(sessions, clock=clock, runs=runs),
        approvals=ApprovalService(sessions, clock=clock),
        worktree_root=root,
    )


def report(done: Pass) -> None:
    for run_id in done.started:
        typer.echo(f"run {run_id} started")
    for run_id in done.finished:
        typer.echo(f"run {run_id} finished")
    for report in done.reports:
        for wakeup_id, verdict in report.waiting.items():
            typer.echo(f"wakeup {wakeup_id} waits: {verdict}")
        for run_id in report.timed_out:
            typer.echo(f"run {run_id} timed out")
        for run_id in report.reaped:
            typer.echo(f"run {run_id} reaped: no heartbeat")
    for approval in done.pushes.requested:
        branch = approval.payload["branch"]
        typer.echo(f"approval {approval.id} pending: push {branch}")
    for run_id, reason in done.pushes.skipped.items():
        typer.echo(f"run {run_id}: {reason}")


def run(
    loop: Annotated[
        bool, typer.Option("--loop", help="Keep ticking until interrupted (Ctrl-C).")
    ] = False,
    ticks: Annotated[
        int, typer.Option(min=0, help="With --loop, stop after this many ticks; 0 means never.")
    ] = 0,
) -> None:
    """Run one scheduler pass and wait for the runs it starts, or loop with --loop."""
    config = settings()
    clock = SystemClock()

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        engine = build_engine(sessions, config, clock)
        if not loop:
            report(await engine.one_pass())
            return
        done = 0
        try:
            while True:
                report(await engine.tick())
                done += 1
                if done == ticks:
                    break
                await clock.sleep(get_scheduler_settings().tick_seconds)
        finally:
            await engine.scheduler.shutdown()

    run_with_database(job, config)
