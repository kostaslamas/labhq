"""`labhq serve`: the MCP server and the background loops in one process."""

from typing import Annotated

import httpx
import typer
import uvicorn

from labhq.cli.context import Context, execute, fail
from labhq.cli.engine import Engine
from labhq.mcp.auth import ensure_token
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import default_registry
from labhq.notify import Dispatcher, NotifyError, NotifySettings, build_notifier

HTTP_TIMEOUT_SECONDS = 10.0


def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8787,
) -> None:
    """Run the MCP server, the scheduler, notifications and status ingestion until stopped.

    Stop it with Ctrl-C or SIGTERM; live runs are interrupted and the exit code is 0.
    """

    # Imported here: `labhq.program` imports `labhq.cli`, whose package init imports this module.
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
                notifier = build_notifier(settings, client, context.settings.data_dir)
            except NotifyError as error:
                fail(str(error))
            services = Services(
                context,
                Engine(context),
                Dispatcher(context.sessions, notifier, clock=context.clock, settings=settings),
            )
            # No access log: the secret path would land in it.
            config = uvicorn.Config(
                build_app(default_registry, secret), host=host, port=port, access_log=False
            )
            program = Program(
                services,
                default_loops,
                ProgramServer(config),
                clock=context.clock,
                settings=get_program_settings(),
            )
            typer.echo(f"Connector URL: http://{host}:{port}/mcp/{secret}")
            try:
                await program.run()
            except ProgramError as error:
                fail(str(error))

    try:
        execute(body)
    except OSError as error:
        fail(f"cannot store the token: {error.strerror or error}")
