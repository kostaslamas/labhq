"""`labhq serve`: the API, the MCP server and the background loops in one process."""

from typing import Annotated

import httpx
import typer
import uvicorn

from labhq.callcenter.calls import SchedulerInterrupter
from labhq.cli.context import Context, execute, fail
from labhq.cli.engine import Engine
from labhq.mcp.auth import ensure_token
from labhq.mcp.server import build_app
from labhq.mcp.tools.calls import attach_interrupter
from labhq.mcp.tools.registry import default_registry
from labhq.notify import Dispatcher, NotifyError, NotifySettings, build_notifier

HTTP_TIMEOUT_SECONDS = 10.0


def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8787,
) -> None:
    """Run the API and MCP server, the scheduler, notifications and status ingestion until stopped.

    Stop it with Ctrl-C or SIGTERM; live runs are interrupted and the exit code is 0.
    """

    # Imported here: `labhq.program` and `labhq.api` import `labhq.cli`, whose package init
    # imports this module.
    from labhq.api import create_server_app
    from labhq.api.settings import get_api_settings, ui_absent_reason
    from labhq.program import (
        Program,
        ProgramError,
        ProgramServer,
        Services,
        default_loops,
        get_program_settings,
    )

    async def body(context: Context) -> None:
        secret = ensure_token(context.settings.data_dir)
        settings = NotifySettings()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            try:
                notifier = build_notifier(
                    settings, client, context.settings.data_dir, sessions=context.sessions
                )
            except NotifyError as error:
                fail(str(error))
            services = Services(
                context,
                Engine(context),
                Dispatcher(context.sessions, notifier, clock=context.clock, settings=settings),
            )
            attach_interrupter(SchedulerInterrupter(services.engine.scheduler))
            # No access log: the secret path would land in it.
            mcp_app = build_app(default_registry, secret)
            api_settings = get_api_settings()
            config = uvicorn.Config(
                create_server_app(context, mcp_app, settings=api_settings),
                host=host,
                port=port,
                access_log=False,
            )
            program = Program(
                services,
                default_loops,
                ProgramServer(config),
                clock=context.clock,
                settings=get_program_settings(),
            )
            typer.echo(f"Connector URL: http://{host}:{port}/mcp/{secret}")
            if absent := ui_absent_reason(api_settings):
                typer.echo(absent, err=True)
            try:
                await program.run()
            except ProgramError as error:
                fail(str(error))

    try:
        execute(body)
    except OSError as error:
        fail(f"cannot store the token: {error.strerror or error}")
