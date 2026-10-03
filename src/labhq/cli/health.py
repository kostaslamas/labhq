"""`labhq health`: the latest sample of each metric per host, and the open incidents."""

from dataclasses import dataclass
from typing import Annotated

import typer
from sqlalchemy import func, select

from labhq.cli.context import Context, execute
from labhq.cli.render import incident_line, sample_line
from labhq.db.enums import IncidentStatus
from labhq.db.models import HealthRule, HealthSample, Host, Incident
from labhq.health.monitor import HealthMonitor
from labhq.health.settings import HealthSettings


@dataclass
class HealthView:
    samples: list[tuple[str, HealthSample]]
    incidents: list[tuple[Incident, str, str]]


async def latest_samples(context: Context) -> list[tuple[str, HealthSample]]:
    latest = (
        select(HealthSample.host_id, func.max(HealthSample.sampled_at).label("at"))
        .group_by(HealthSample.host_id)
        .subquery()
    )
    query = (
        select(Host.name, HealthSample)
        .join(Host, Host.id == HealthSample.host_id)
        .join(
            latest,
            (latest.c.host_id == HealthSample.host_id) & (latest.c.at == HealthSample.sampled_at),
        )
        .order_by(Host.name, HealthSample.metric, HealthSample.subject)
    )
    async with context.sessions() as db:
        return [(name, sample) for name, sample in await db.execute(query)]


async def open_incidents(context: Context) -> list[tuple[Incident, str, str]]:
    query = (
        select(Incident, HealthRule.name, Host.name)
        .join(HealthRule, HealthRule.id == Incident.rule_id)
        .join(Host, Host.id == Incident.host_id)
        .where(Incident.status == IncidentStatus.OPEN)
        .order_by(Incident.opened_at, Incident.id)
    )
    async with context.sessions() as db:
        return [(incident, rule, host) for incident, rule, host in await db.execute(query)]


def health(
    collect: Annotated[
        bool, typer.Option("--collect", help="Sample this machine and evaluate the rules first.")
    ] = False,
) -> None:
    """Show the latest health samples per host and the open incidents."""

    async def body(context: Context) -> HealthView:
        if collect:
            await HealthMonitor(context.sessions, context.clock, HealthSettings()).tick()
        return HealthView(await latest_samples(context), await open_incidents(context))

    view = execute(body)
    for host, sample in view.samples:
        typer.echo(sample_line(host, sample))
    if not view.samples:
        typer.echo("no samples yet; run `labhq health --collect`")
    for incident, rule, host in view.incidents:
        typer.echo(incident_line(incident, rule, host))
    typer.echo(f"{len(view.incidents)} open incident(s)")
