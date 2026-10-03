"""`labhq mcp`: serve the Call Center connector and manage its token."""

from typing import Annotated

import typer
import uvicorn

from labhq.approvals.registry import UnknownEntryError
from labhq.cli.context import fail, load_settings
from labhq.expose import ExposureError, exposures, serve_exposed
from labhq.mcp.auth import ensure_token, write_token
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import default_registry

mcp_app = typer.Typer(help="The Call Center MCP server.", no_args_is_help=True)


def _token(*, rotate: bool) -> str:
    data_dir = load_settings().data_dir
    try:
        return write_token(data_dir) if rotate else ensure_token(data_dir)
    except OSError as error:
        fail(f"cannot store the token under {data_dir}: {error.strerror or error}")


@mcp_app.command()
def token(
    rotate: Annotated[bool, typer.Option("--rotate", help="Replace the token.")] = False,
) -> None:
    """Show the connector token, or replace it."""
    typer.echo(_token(rotate=rotate))


@mcp_app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8787,
    expose: Annotated[
        str | None,
        typer.Option(help="Publish the server through this exposure, for example quick-tunnel."),
    ] = None,
) -> None:
    """Run the MCP server and print the connector URL once."""
    secret = _token(rotate=False)
    app = build_app(default_registry, secret)
    if expose is None:
        typer.echo(f"Connector URL: http://{host}:{port}/mcp/{secret}")
        # No access log: the secret path would land in it.
        uvicorn.run(app, host=host, port=port, access_log=False)
        return
    try:
        adapter = exposures.get(expose)()
    except UnknownEntryError:
        fail(f"unknown exposure {expose!r}; available: {', '.join(exposures)}")
    # An exposure that fails never falls back to a local-only server.
    try:
        serve_exposed(
            app,
            host=host,
            port=port,
            secret=secret,
            adapter=adapter,
            announce=lambda url: typer.echo(f"Connector URL: {url}"),
        )
    except ExposureError as error:
        fail(str(error))
