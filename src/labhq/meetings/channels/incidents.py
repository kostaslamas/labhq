"""Incidents to the `infra` channel: one thread per incident, opened and resolved (plan §2.2).

Read from the `incidents` table on every pass rather than hooked into the health loop, so the
rule engine stays unaware of chat. The idempotency key makes a transition one post however
many passes see it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import HealthRule, Host, Incident
from labhq.meetings.channels.outbox import Destination, enqueue
from labhq.meetings.channels.personas import system_persona
from labhq.meetings.channels.settings import ChannelSettings


@dataclass(frozen=True)
class Transition:
    kind: str
    # When it happened; None means it has not.
    at: Callable[[Incident], datetime | None]
    text: Callable[[Incident, HealthRule, Host], str]


def _opened(incident: Incident, rule: HealthRule, host: Host) -> str:
    return (
        f"Incident #{incident.id} opened on {host.name}: {rule.name} "
        f"(rule {rule.id}, {rule.type}). {rule.reason}"
    )


def _resolved(incident: Incident, rule: HealthRule, host: Host) -> str:
    return f"Incident #{incident.id} resolved on {host.name}: {rule.name}."


TRANSITIONS = (
    Transition("incident_opened", lambda incident: incident.opened_at, _opened),
    Transition("incident_resolved", lambda incident: incident.resolved_at, _resolved),
)


async def enqueue_incidents(db: AsyncSession, clock: Clock, settings: ChannelSettings) -> int:
    """Queue every recent transition not queued yet; returns how many were new."""
    now = clock.now()
    since = now - timedelta(seconds=settings.incident_lookback_seconds)
    rows = await db.execute(
        select(Incident, HealthRule, Host)
        .join(HealthRule, Incident.rule_id == HealthRule.id)
        .join(Host, Incident.host_id == Host.id)
        .where(or_(Incident.opened_at >= since, Incident.resolved_at >= since))
        .order_by(Incident.id)
    )
    added = 0
    for incident, rule, host in rows.all():
        destination = Destination(
            channel_key=settings.infra_channel,
            channel_name=settings.infra_channel,
            thread_key=f"incident:{incident.id}",
            thread_title=f"Incident #{incident.id}: {rule.name} on {host.name}",
        )
        for transition in TRANSITIONS:
            at = transition.at(incident)
            if at is None or at < since:
                continue
            added += await enqueue(
                db,
                key=f"incident:{incident.id}:{transition.kind}",
                kind=transition.kind,
                destination=destination,
                persona=system_persona(settings),
                text=transition.text(incident, rule, host),
                now=now,
            )
    return added
