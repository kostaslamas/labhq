"""`labhq sessions scan|analyse|close|continue|folder`: the inventory of agent sessions.

`scan` is free (no model, no conversation read). `analyse` only records the approval that
starts one project's analysis; approve it with `labhq approvals approve`.
"""

import asyncio
from typing import Annotated

import typer

from labhq.adoption import AdoptionError, Adoptions
from labhq.approvals import ApprovalService
from labhq.cli.context import CliError, Context, execute
from labhq.cli.render import approval_line
from labhq.inventory import register  # noqa: F401  (registers the approval executors)
from labhq.inventory.analysis import Analyses, AnalysisError
from labhq.inventory.chooser import NoRunnerError
from labhq.inventory.close import SessionCloser
from labhq.inventory.continuing import continue_session
from labhq.inventory.folders import propose
from labhq.inventory.model import Inventory
from labhq.inventory.report import project_report, scope_text
from labhq.inventory.roots import RootError, add_root, effective_scope, remove_root, stored_roots
from labhq.inventory.scoped import scanner_for
from labhq.inventory.service import locate, scan_and_report
from labhq.inventory.settings import get_inventory_settings

sessions_app = typer.Typer(help="Inventory of agent sessions.", no_args_is_help=True)

Project = Annotated[str, typer.Argument(help="The project's folder name or path.")]
ERRORS = (AnalysisError, NoRunnerError, AdoptionError)


async def _scan(context: Context) -> Inventory:
    async with context.sessions() as db:
        scanner = await scanner_for(db, context.clock)
    return await asyncio.to_thread(scanner.scan)


@sessions_app.command("scan")
def scan(
    report: Annotated[
        bool, typer.Option(help="Also file one report per project to the CEO.")
    ] = True,
) -> None:
    """Find every running and saved agent session on this machine, grouped by project."""

    async def body(context: Context) -> None:
        async with context.sessions() as db:
            result = await scan_and_report(db, context.clock, report=report)
            await db.commit()
        for project in result.inventory.projects:
            typer.echo(project_report(project, result.tools))
        for folder in result.inventory.folders:
            typer.echo(
                f"folder manager proposal: {folder.folder} holds {len(folder.projects)} projects"
            )
        if not result.inventory.projects:
            typer.echo("no agent sessions found")
        typer.echo(f"scope: {scope_text(result.inventory)}")

    execute(body)


@sessions_app.command("analyse")
def analyse(project: Project) -> None:
    """Show the estimate for analysing one project and ask for the owner's approval."""

    async def body(context: Context) -> None:
        try:
            request = await Analyses(context.sessions, clock=context.clock).request(project)
        except (AnalysisError, NoRunnerError) as error:
            raise CliError(str(error)) from None
        typer.echo(request.text)

    execute(body)


@sessions_app.command("close")
def close(
    project: Project, pid: Annotated[int, typer.Argument(help="The session's process id.")]
) -> None:
    """Ask to end an idle session's process; the conversation stays saved."""

    async def body(context: Context) -> None:
        found = await _scan(context)
        try:
            _, session = locate(found, project, pid=pid)
            approval = await SessionCloser().request(
                ApprovalService(context.sessions, clock=context.clock), session
            )
        except ERRORS as error:
            raise CliError(str(error)) from None
        typer.echo(approval_line(approval))

    execute(body)


@sessions_app.command("continue")
def continue_(
    project: Project,
    session_id: Annotated[str | None, typer.Option(help="A saved session's id.")] = None,
    pid: Annotated[int | None, typer.Option(help="A running session's process id.")] = None,
) -> None:
    """Adopt a running session, resume a saved one, or hand a Cursor IDE chat to a CLI agent."""

    async def body(context: Context) -> None:
        found = await _scan(context)
        try:
            chosen, session = locate(found, project, session_id=session_id, pid=pid)
            result = await continue_session(
                context.sessions,
                context.clock,
                Adoptions(context.sessions, clock=context.clock),
                session,
                project_name=chosen.name,
                data_dir=context.settings.data_dir,
            )
        except ERRORS as error:
            raise CliError(str(error)) from None
        if result.approval is not None:
            typer.echo(approval_line(result.approval))
        if result.task is not None:
            typer.echo(f"hand-off task {result.task.id}: {result.task.title}")

    execute(body)


@sessions_app.command("folder")
def folder(path: Annotated[str, typer.Argument(help="A proposed parent folder.")]) -> None:
    """Accept a folder-manager proposal: asks for the approval that creates the manager."""

    async def body(context: Context) -> None:
        found = await _scan(context)
        match = [f for f in found.folders if str(f.folder) == path or f.folder.name == path]
        if len(match) != 1:
            raise CliError(f"no single folder-manager proposal for {path!r}")
        approvals = ApprovalService(context.sessions, clock=context.clock)
        typer.echo(approval_line(await propose(approvals, match[0])))

    execute(body)


roots_app = typer.Typer(
    help="The folders the scan looks in.", invoke_without_command=True, no_args_is_help=False
)
sessions_app.add_typer(roots_app, name="roots")


@roots_app.callback()
def roots(ctx: typer.Context) -> None:
    """List the scan roots; `add` and `remove` change them."""
    if ctx.invoked_subcommand is None:
        roots_list()


@roots_app.command("list")
def roots_list() -> None:
    """List the folders the scan looks in, and the exclusions."""

    async def body(context: Context) -> None:
        settings = get_inventory_settings()
        async with context.sessions() as db:
            kept = await stored_roots(db)
            scope = await effective_scope(db, settings)
        if scope.machine_wide:
            typer.echo("machine-wide: no scope set")
            return
        for root in scope.roots:
            typer.echo(str(root))
        for pattern in scope.exclude:
            typer.echo(f"excluded: {pattern}")
        if kept and not set(kept) <= {str(r) for r in scope.roots}:
            typer.echo("note: a stored root no longer resolves to the same folder")

    execute(body)


@roots_app.command("add")
def roots_add(path: Annotated[str, typer.Argument(help="A folder that holds projects.")]) -> None:
    """Add a folder to the scan roots. `/` and a missing folder are refused."""

    async def body(context: Context) -> None:
        async with context.sessions() as db:
            try:
                checked = await add_root(db, context.clock, path)
            except RootError as error:
                raise CliError(str(error)) from None
            await db.commit()
        typer.echo(f"added {checked.path}")
        if checked.warning:
            typer.echo(f"warning: {checked.warning}")

    execute(body)


@roots_app.command("remove")
def roots_remove(path: Annotated[str, typer.Argument(help="A root to stop searching.")]) -> None:
    """Remove a folder from the scan roots."""

    async def body(context: Context) -> None:
        async with context.sessions() as db:
            removed = await remove_root(db, context.clock, path)
            await db.commit()
        if not removed:
            raise CliError(f"{path} is not one of the scan roots")
        typer.echo(f"removed {path}")

    execute(body)
