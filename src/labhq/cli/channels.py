"""`labhq channels`: list, add, test and remove the places the owner is notified."""

from typing import Annotated

import httpx
import typer

from labhq.channels import (
    ChannelConfigError,
    ChannelNotFoundError,
    ChannelRuntime,
    channel_kinds,
    list_channels,
    remove_channel,
)
from labhq.channels.setup import create_and_test
from labhq.cli.context import Context, execute, fail
from labhq.notify import NotifySettings

channels_app = typer.Typer(help="Where labhq notifies you.", no_args_is_help=True)

HTTP_TIMEOUT_SECONDS = 10.0


def _parse(pairs: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for pair in pairs:
        name, separator, value = pair.partition("=")
        if not separator:
            fail(f"{pair!r} should look like name=value")
        values[name] = value
    return values


@channels_app.command("list")
def list_command() -> None:
    """Show every channel and the result of its last test."""

    async def body(context: Context) -> list[str]:
        async with context.sessions() as db:
            rows = await list_channels(db)
        return [
            f"{row.id}\t{row.name}\t{row.kind}\t"
            f"{'on' if row.enabled else 'off'}\t"
            f"{'untested' if row.last_test_ok is None else 'ok' if row.last_test_ok else 'failed'}"
            for row in rows
        ]

    lines = execute(body)
    typer.echo("\n".join(lines) if lines else "no channels; the configured notifier is used")


@channels_app.command("add")
def add_command(
    kind: Annotated[str, typer.Argument(help=f"One of: {', '.join(channel_kinds)}.")],
    name: Annotated[str, typer.Option(help="What you call it, for example 'my phone'.")],
    field: Annotated[
        list[str] | None, typer.Option(help="A setting as name=value; repeat for several.")
    ] = None,
) -> None:
    """Add a channel and send its test message. A secret is asked for hidden, never as an option."""
    if kind not in channel_kinds:
        fail(f"unknown channel kind {kind!r}; available: {', '.join(channel_kinds)}")
    values = _parse(field or [])
    for item in channel_kinds.get(kind).fields:
        if item.secret and item.name not in values:
            values[item.name] = typer.prompt(item.label, hide_input=True)

    async def body(context: Context) -> tuple[int, str | None]:
        settings = NotifySettings()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            runtime = ChannelRuntime(
                context.sessions, client, context.settings.data_dir, context.clock, settings
            )
            try:
                row, error = await create_and_test(
                    context.sessions,
                    runtime,
                    context.settings.data_dir,
                    context.clock,
                    kind=kind,
                    name=name,
                    values=values,
                )
            except ChannelConfigError as refusal:
                fail(str(refusal))
        return row.id, error

    channel_id, error = execute(body)
    if error is not None:
        fail(f"channel {channel_id} added, but its test message failed: {error}")
    typer.echo(f"channel {channel_id} added; its test message arrived")


@channels_app.command("test")
def test_command(channel_id: int) -> None:
    """Send the test message to one channel."""

    async def body(context: Context) -> str | None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            runtime = ChannelRuntime(
                context.sessions,
                client,
                context.settings.data_dir,
                context.clock,
                NotifySettings(),
            )
            try:
                return await runtime.test(channel_id)
            except ChannelNotFoundError:
                fail(f"no channel {channel_id}")

    error = execute(body)
    if error is not None:
        fail(f"the test message failed: {error}")
    typer.echo("the test message arrived")


@channels_app.command("remove")
def remove_command(channel_id: int) -> None:
    """Remove a channel and its secret."""

    async def body(context: Context) -> None:
        async with context.sessions() as db:
            try:
                await remove_channel(db, context.settings.data_dir, channel_id)
            except ChannelNotFoundError:
                fail(f"no channel {channel_id}")
            await db.commit()

    execute(body)
    typer.echo(f"channel {channel_id} removed")
