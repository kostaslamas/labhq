"""`labhq hosts add|list|test`: the machines labhq watches over SSH, and one test collection."""

from datetime import timedelta
from typing import Annotated

import asyncssh
import typer
from sqlalchemy import select

from labhq.cli.context import CliError, Context, execute, fail
from labhq.db.enums import HostStatus
from labhq.db.models import Host
from labhq.health import collectors
from labhq.health.collector import Reading
from labhq.health.collectors import CollectionSettings, HostTarget, ProbeContext
from labhq.health.monitor import HostCollection, collect_host
from labhq.health.settings import HealthSettings
from labhq.health.ssh import (
    SshError,
    SshSettings,
    SshTarget,
    fetch_host_key,
    fingerprint,
    trust_host_key,
)

hosts_app = typer.Typer(help="Add, list and test the hosts labhq watches.", no_args_is_help=True)


def _target(address: str) -> SshTarget:
    try:
        return SshTarget.parse(address)
    except ValueError as error:
        raise CliError(f"bad address {address!r}: {error}") from error


async def _presented_key(target: SshTarget) -> asyncssh.SSHKey:
    try:
        return await fetch_host_key(target, SshSettings())
    except SshError as error:
        raise CliError(str(error)) from error


async def _save_host(
    context: Context, name: str, address: str, user: str, intervention_user: str | None
) -> Host:
    now = context.clock.now()
    async with context.sessions() as db, db.begin():
        host = await db.scalar(select(Host).where(Host.name == name))
        if host is None:
            host = Host(name=name, created_at=now, status=HostStatus.UNKNOWN)
            db.add(host)
        elif host.is_local:
            raise CliError(f"{name} is this machine; it needs no SSH")
        host.address = address
        host.ssh_user = user
        host.intervention_user = intervention_user
        host.updated_at = now
    return host


@hosts_app.command("add")
def add(
    name: Annotated[str, typer.Argument(help="A name for the host, unique in labhq.")],
    address: Annotated[str, typer.Option(help="host, host:port or [v6]:port.")],
    user: Annotated[str, typer.Option(help="The read-only SSH user that collection logs in as.")],
    intervention_user: Annotated[
        str | None,
        typer.Option(help="The user approved interventions run as. Without one, none run."),
    ] = None,
    expected_fingerprint: Annotated[
        str | None,
        typer.Option("--fingerprint", help="Trust the key only if it has this SHA256 fingerprint."),
    ] = None,
) -> None:
    """Add or update an SSH host after you confirm the fingerprint of its host key."""
    target = _target(address)

    async def presented(_: Context) -> asyncssh.SSHKey:
        return await _presented_key(target)

    key = execute(presented)
    shown = fingerprint(key)
    typer.echo(f"{name} ({target}) presents {key.get_algorithm()} key {shown}")
    if expected_fingerprint is not None:
        if expected_fingerprint != shown:
            fail(f"the host key fingerprint is {shown}, not {expected_fingerprint}")
    elif not typer.confirm("Trust this host key?", default=False):
        fail("host key not trusted; nothing recorded")
    trust_host_key(SshSettings().known_hosts(), target, key)

    async def save(context: Context) -> Host:
        return await _save_host(context, name, address, user, intervention_user)

    host = execute(save)
    typer.echo(f"host {host.id} {host.name}: {user}@{target}, key trusted")


def host_line(host: Host) -> str:
    target = HostTarget.of(host)
    where = "this machine" if host.is_local else f"{host.ssh_user}@{host.address}"
    fixer = host.intervention_user or "none"
    return (
        f"host {host.id} {host.name} [{target.kind}] {where}: {host.status}, "
        f"interventions as {fixer}"
    )


@hosts_app.command("list")
def list_hosts() -> None:
    """List the hosts labhq watches, with their kind and status."""

    async def body(context: Context) -> list[Host]:
        async with context.sessions() as db:
            return list(await db.scalars(select(Host).order_by(Host.name)))

    hosts = execute(body)
    for host in hosts:
        typer.echo(host_line(host))
    if not hosts:
        typer.echo("no hosts yet; run `labhq hosts add` or `labhq health --collect`")


def reading_line(reading: Reading) -> str:
    subject = f" [{reading.subject}]" if reading.subject else ""
    return f"{reading.metric}{subject} = {reading.value:g}"


@hosts_app.command("test")
def test(name: Annotated[str, typer.Argument(help="The host's name.")]) -> None:
    """Collect once from a host and print the readings, without storing them."""

    async def body(context: Context) -> HostCollection:
        async with context.sessions() as db:
            host = await db.scalar(select(Host).where(Host.name == name))
        if host is None:
            raise CliError(f"no host named {name}; see `labhq hosts list`")
        now = context.clock.now()
        probe_context = ProbeContext(
            now=now,
            since=now - timedelta(seconds=HealthSettings().sample_interval_seconds),
            certificates=CollectionSettings().certificates_for(host.name),
        )
        target = HostTarget.of(host)
        return await collect_host(target, probe_context, collectors.default_collectors)

    collection = execute(body)
    if collection.error is not None:
        fail(f"collection from {name} failed: {collection.error}")
    for reading in collection.readings:
        typer.echo(reading_line(reading))
    typer.echo(f"{len(collection.readings)} reading(s) from {name}")
