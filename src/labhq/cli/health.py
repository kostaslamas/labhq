"""`labhq health`: the latest samples of every host and the incidents still open."""

from typing import Annotated

import typer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.cli.runtime import run_with_database
from labhq.clock import SystemClock
from labhq.db.enums import IncidentStatus
from labhq.db.models import HealthRule, HealthSample, Host, Incident
from labhq.health.monitor import HealthMonitor
from labhq.health.settings import HealthSettings


async def latest_samples(db: AsyncSession) -> list[tuple[Host, HealthSample]]:
    # The collector stamps one pass with one instant, so the newest instant is one pass.
    newest = (
        select(HealthSample.host_id, func.max(HealthSample.sampled_at).label("sampled_at"))
        .group_by(HealthSample.host_id)
        .subquery()
    )
    rows = await db.execute(
        select(Host, HealthSample)
        .join(HealthSample, HealthSample.host_id == Host.id)
        .join(
            newest,
            (newest.c.host_id == HealthSample.host_id)
            & (newest.c.sampled_at == HealthSample.sampled_at),
        )
        .order_by(Host.name, HealthSample.metric, HealthSample.subject)
    )
    return [(host, sample) for host, sample in rows]


async def open_incidents(db: AsyncSession) -> list[tuple[Incident, HealthRule, Host]]:
    rows = await db.execute(
        select(Incident, HealthRule, Host)
        .join(HealthRule, HealthRule.id == Incident.rule_id)
        .join(Host, Host.id == Incident.host_id)
        .where(Incident.status == IncidentStatus.OPEN)
        .order_by(Incident.opened_at, Incident.id)
    )
    return [(incident, rule, host) for incident, rule, host in rows]


def health(
    collect: Annotated[
        bool, typer.Option("--collect", help="Sample this machine and evaluate the rules first.")
    ] = False,
) -> None:
    """Show the latest health samples and the open incidents."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        if collect:
            await HealthMonitor(sessions, SystemClock(), HealthSettings()).tick()
        async with sessions() as db:
            samples = await latest_samples(db)
            incidents = await open_incidents(db)
        if not samples:
            typer.echo("no samples yet (labhq health --collect takes one)")
        for host, sample in samples:
            subject = f"[{sample.subject}]" if sample.subject else ""
            stamp = sample.sampled_at.isoformat(timespec="seconds")
            typer.echo(f"{host.name}  {sample.metric}{subject}  {sample.value:g}  {stamp}")
        typer.echo(f"{len(incidents)} open incidents")
        for incident, rule, host in incidents:
            opened = incident.opened_at.isoformat(timespec="seconds")
            typer.echo(f"incident {incident.id}  {rule.name}  {host.name}  since {opened}")

    run_with_database(job)
