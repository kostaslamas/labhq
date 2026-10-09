"""`labhq federation invite|add|list|revoke|poll|sync`: pair two labhq instances (issue #188).

`invite` and `poll` run on the downstream instance, `add` on the upstream one. `list` and
`revoke` work on whichever side holds the thing: nodes upstream, invites downstream.
"""

import asyncio
from typing import Annotated

import typer

from labhq.cli.context import CliError, Context, execute
from labhq.db.models import FederationInvite, FederationNode
from labhq.federation.a2a.sync import SyncResult, a2a_nodes, sync_once
from labhq.federation.invites import Invites
from labhq.federation.keys import ALL_SCOPES
from labhq.federation.nodes import Nodes
from labhq.federation.poller import PollResult, UpstreamClient, poll_once
from labhq.federation.settings import FederationSettings
from labhq.money import format_micros, usd_to_micros

federation_app = typer.Typer(
    help="Let this labhq's CEO manage another labhq, or be managed by one.",
    no_args_is_help=True,
)

Scopes = Annotated[
    list[str] | None,
    typer.Option("--scope", help=f"What the key may do: {', '.join(ALL_SCOPES)}. Repeatable."),
]


def node_line(node: FederationNode) -> str:
    cap = format_micros(node.spend_cap_micros) if node.spend_cap_micros is not None else "none"
    state = "revoked" if node.revoked_at is not None else "active"
    transport = f", A2A at {node.a2a_url}" if node.a2a_url else ""
    return (
        f"node {node.id} {node.name} ({node.url}): {state}, scopes {','.join(node.scopes)}, "
        f"manager agent {node.manager_agent_id}, per-order cap {cap}{transport}"
    )


def invite_line(invite: FederationInvite) -> str:
    state = "revoked" if invite.revoked_at is not None else "active"
    label = f" {invite.label}" if invite.label else ""
    return f"invite {invite.id}{label}: {state}, scopes {','.join(invite.scopes)}"


@federation_app.command("invite")
def invite(
    label: Annotated[str, typer.Option(help="A note to tell invites apart.")] = "",
    scope: Scopes = None,
) -> None:
    """Print a one-time pairing key for the upstream instance. Only its hash is stored."""

    async def body(context: Context) -> tuple[FederationInvite, str]:
        made = await Invites(context.sessions, clock=context.clock).create(
            label=label, scopes=scope or ALL_SCOPES
        )
        return made.invite, made.key

    created, key = execute(body)
    typer.echo(invite_line(created))
    typer.echo("Pairing key (shown once, store it nowhere but the upstream's `add`):")
    typer.echo(key)
    typer.echo("On this machine set LABHQ_FEDERATION_UPSTREAM_KEY to it and run `federation poll`.")


@federation_app.command("add")
def add(
    url: Annotated[str, typer.Argument(help="The downstream instance's URL, for your reference.")],
    key: Annotated[str, typer.Argument(help="The pairing key its `invite` printed.")],
    project: Annotated[
        str, typer.Option(help="The project the remote manager joins (id or name).")
    ],
    name: Annotated[str | None, typer.Option(help="Node name. Default: the URL's host.")] = None,
    spend_cap_usd: Annotated[
        str | None, typer.Option(help="Per-order spend cap attached to every order, in USD.")
    ] = None,
    a2a_url: Annotated[
        str | None,
        typer.Option(
            help="The node's A2A base URL. Set: orders are sent there (`federation sync`). "
            "Unset: the node polls for them."
        ),
    ] = None,
    scope: Scopes = None,
) -> None:
    """Register a downstream instance as a remote manager in the CEO's org chart."""
    try:
        cap = usd_to_micros(spend_cap_usd) if spend_cap_usd is not None else None
    except (ValueError, ArithmeticError) as error:
        raise CliError(f"bad spend cap {spend_cap_usd!r}: {error}") from error

    async def body(context: Context) -> FederationNode:
        added = await Nodes(context.sessions, clock=context.clock).add(
            url,
            key,
            project=project,
            name=name,
            scopes=scope or ALL_SCOPES,
            spend_cap_micros=cap,
            a2a_url=a2a_url,
        )
        return added.node

    typer.echo(node_line(execute(body)))


@federation_app.command("list")
def list_all() -> None:
    """Nodes registered here and invites printed here."""

    async def body(context: Context) -> tuple[list[FederationNode], list[FederationInvite]]:
        nodes = await Nodes(context.sessions, clock=context.clock).list()
        invites = await Invites(context.sessions, clock=context.clock).list()
        return nodes, invites

    nodes, invites = execute(body)
    for line in [*map(node_line, nodes), *map(invite_line, invites)] or ["nothing is paired"]:
        typer.echo(line)


@federation_app.command("revoke")
def revoke(
    reference: Annotated[str, typer.Argument(help="A node's id or name, or an invite's id.")],
    invite_id: Annotated[
        bool, typer.Option("--invite", help="REFERENCE is an invite's id, not a node.")
    ] = False,
) -> None:
    """Refuse a key from now on: a node's next poll fails; an invite stops this side's polling."""

    async def body(context: Context) -> str:
        if invite_id:
            if not reference.isdigit():
                raise CliError("an invite is named by its numeric id")
            revoked = await Invites(context.sessions, clock=context.clock).revoke(int(reference))
            return invite_line(revoked)
        return node_line(await Nodes(context.sessions, clock=context.clock).revoke(reference))

    typer.echo(execute(body))


@federation_app.command("poll")
def poll(
    every: Annotated[
        float | None, typer.Option(help="Keep polling, pausing this many seconds between rounds.")
    ] = None,
) -> None:
    """Dial the upstream once: take its orders and post this instance's reports."""
    settings = FederationSettings()

    async def body(context: Context) -> PollResult:
        async with UpstreamClient(settings) as client:
            while True:
                result = await poll_once(context.sessions, context.clock, client, settings)
                typer.echo(
                    f"orders received {result.orders_received}, reports sent {result.reports_sent}"
                )
                if every is None:
                    return result
                await asyncio.sleep(every)

    execute(body)


@federation_app.command("sync")
def sync(
    every: Annotated[
        float | None, typer.Option(help="Keep syncing, pausing this many seconds between rounds.")
    ] = None,
) -> None:
    """Send queued orders to A2A nodes and read their tasks back as reports."""
    settings = FederationSettings()

    async def body(context: Context) -> SyncResult:
        async with context.sessions() as db:
            if not await a2a_nodes(db):
                raise CliError(
                    "no node has an A2A URL; register one with `federation add --a2a-url`"
                )
        while True:
            result = await sync_once(context.sessions, context.clock, settings)
            typer.echo(
                f"orders sent {result.orders_sent}, reports applied {result.reports_applied}"
            )
            for name, reason in result.failures.items():
                typer.echo(f"node {name}: {reason}")
            if every is None:
                return result
            await asyncio.sleep(every)

    execute(body)
