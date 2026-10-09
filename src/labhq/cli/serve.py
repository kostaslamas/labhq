"""`labhq serve`: the API, the MCP server and the background loops in one process."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn
from pydantic import ValidationError

from labhq.auth.public_url import load_public_url, store_public_url
from labhq.auth.settings import AuthSettings
from labhq.channels import ChannelRuntime, FanOutNotifier
from labhq.cli.context import Context, execute, fail
from labhq.cli.engine import Engine
from labhq.expose import ExposureError, expose_running, exposures, verify_connector
from labhq.mcp.auth import ensure_token
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import default_registry
from labhq.notify import Dispatcher, NotifyError, NotifySettings, build_notifier

HTTP_TIMEOUT_SECONDS = 10.0


def remember_public_url(data_dir: Path, given: str | None) -> None:
    """Persist the address from `--public-url`, or from `LABHQ_PUBLIC_URL` when set."""
    try:
        settings = AuthSettings(public_url=given) if given else AuthSettings()
    except ValidationError as error:
        fail(f"--public-url is not usable: {error.errors()[0]['msg']}")
    if settings.public_url is None or settings.public_url == load_public_url(data_dir):
        return
    try:
        store_public_url(data_dir, settings.public_url)
    except OSError as error:
        fail(f"cannot store the public URL: {error.strerror or error}")


def _is_terminal() -> bool:
    return sys.stdout.isatty()


def _announce(url: str, secret: str) -> None:
    """Print the connector URL; off a terminal (a systemd journal) the token stays out of it."""
    if _is_terminal():
        typer.echo(f"Connector URL: {url}")
        return
    typer.echo(
        f"Connector URL: {url.removesuffix(secret)} (run `labhq mcp token` to see the token)"
    )


def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8787,
    public_url: Annotated[
        str | None,
        typer.Option(
            help=(
                "The address you reach labhq on from outside, for example "
                "https://labhq.example.org. "
                "Kept in the data directory, so `labhq passkey enroll` links to it."
            )
        ),
    ] = None,
    expose: Annotated[
        str | None,
        typer.Option(help="Publish the server through this exposure, for example quick-tunnel."),
    ] = None,
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

    if expose is not None and expose not in exposures:
        fail(f"unknown exposure {expose!r}; available: {', '.join(exposures)}")

    async def body(context: Context) -> None:
        remember_public_url(context.settings.data_dir, public_url)
        secret = ensure_token(context.settings.data_dir)
        settings = NotifySettings()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            try:
                notifier = build_notifier(settings, client, context.settings.data_dir)
            except NotifyError as error:
                fail(str(error))
            # Every enabled channel gets each message; with none, the notifier above does.
            channels = ChannelRuntime(
                context.sessions,
                client,
                context.settings.data_dir,
                context.clock,
                settings,
            )
            services = Services(
                context,
                Engine(context),
                Dispatcher(
                    context.sessions,
                    FanOutNotifier(channels, notifier),
                    clock=context.clock,
                    settings=settings,
                ),
            )
            # No access log: the secret path would land in it.
            mcp_app = build_app(default_registry, secret)
            api_settings = get_api_settings()
            server = ProgramServer(
                uvicorn.Config(
                    create_server_app(context, mcp_app, settings=api_settings),
                    host=host,
                    port=port,
                    access_log=False,
                )
            )
            program = Program(
                services,
                default_loops,
                server,
                clock=context.clock,
                settings=get_program_settings(),
            )
            exposing = None
            if expose is None:
                _announce(f"http://{host}:{port}/mcp/{secret}", secret)
            else:
                exposing = asyncio.create_task(
                    expose_running(
                        server,
                        port=port,
                        secret=secret,
                        adapter=exposures.get(expose)(),
                        announce=lambda url: _announce(url, secret),
                        clock=context.clock,
                        verify=verify_connector,
                    )
                )
                # A failed exposure stops the program rather than leaving a private server.
                exposing.add_done_callback(
                    lambda task: None if task.cancelled() else program.request_stop()
                )
            if absent := ui_absent_reason(api_settings):
                typer.echo(absent, err=True)
            try:
                await program.run()
            except ProgramError as error:
                fail(str(error))
            finally:
                if exposing is not None:
                    exposing.cancel()
                    results = await asyncio.gather(exposing, return_exceptions=True)
                    if isinstance(results[0], ExposureError):
                        fail(str(results[0]))

    try:
        execute(body)
    except OSError as error:
        fail(f"cannot store the token: {error.strerror or error}")
