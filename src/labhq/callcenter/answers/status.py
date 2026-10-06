"""`health`: hosts, the latest samples that matter and open incidents, in plain sentences."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.phrasing import clean
from labhq.clock import Clock
from labhq.db.enums import HostStatus, IncidentStatus
from labhq.db.models import HealthRule, HealthSample, Host, Incident
from labhq.scheduler.capacity import capacity
from labhq.speech import join_sentences, say_ago, say_count, speakable

LISTED = 5


@dataclass(frozen=True)
class Spoken:
    label: str
    say_value: Callable[[float], str]


def _percent(value: float) -> str:
    return f"{value:.0f} percent"


def _degrees(value: float) -> str:
    return f"{value:.0f} degrees"


def _load(value: float) -> str:
    return f"{value:.1f}"


def _gigabytes(value: float) -> str:
    return f"{value / 1e9:.1f} gigabytes"


# Data, not branches: a new metric family is a new row. Unknown metrics fall back to raw text.
METRICS: dict[str, Spoken] = {
    "cpu.percent": Spoken("processor use", _percent),
    "memory.percent": Spoken("memory use", _percent),
    "memory.available_bytes": Spoken("free memory", _gigabytes),
    "disk.percent": Spoken("disk use", _percent),
    "temperature.celsius": Spoken("temperature", _degrees),
    "load.1m": Spoken("load over one minute", _load),
    "load.5m": Spoken("load over five minutes", _load),
    "load.15m": Spoken("load over fifteen minutes", _load),
}

_HOST_SENTENCES: dict[HostStatus, str] = {
    HostStatus.UP: "{name} is up",
    HostStatus.DEGRADED: "{name} is degraded",
    HostStatus.DOWN: "{name} is down",
    HostStatus.UNKNOWN: "{name} has not reported yet",
}


def _say_metric(metric: str, subject: str | None, value: float) -> str:
    spoken = METRICS.get(metric) or Spoken(clean(metric), lambda v: f"{v:.1f}")
    where = f" on {clean(subject)}" if subject else ""
    return f"{spoken.label}{where} is {spoken.say_value(value)}"


async def _hosts(db: AsyncSession) -> list[Host]:
    rows = await db.scalars(select(Host).order_by(Host.name))
    return list(rows.all())


async def _watched_metrics(db: AsyncSession) -> set[str]:
    """Metrics some enabled rule watches: the ones the owner cares about hearing."""
    rows = await db.scalars(select(HealthRule.params).where(HealthRule.enabled.is_(True)))
    return {str(params["metric"]) for params in rows.all() if params.get("metric")}


async def _latest_samples(db: AsyncSession, metrics: set[str]) -> list[tuple[str, HealthSample]]:
    if not metrics:
        return []
    key = (HealthSample.host_id, HealthSample.metric, HealthSample.subject)
    newest = (
        select(*key, func.max(HealthSample.sampled_at).label("at"))
        .where(HealthSample.metric.in_(metrics))
        .group_by(*key)
        .subquery()
    )
    rows = await db.execute(
        select(Host.name, HealthSample)
        .join(Host, Host.id == HealthSample.host_id)
        .join(
            newest,
            (newest.c.host_id == HealthSample.host_id)
            & (newest.c.metric == HealthSample.metric)
            & (newest.c.subject.is_not_distinct_from(HealthSample.subject))
            & (newest.c.at == HealthSample.sampled_at),
        )
        .order_by(Host.name, HealthSample.metric, HealthSample.subject)
    )
    return [(name, sample) for name, sample in rows.all()]


async def _open_incidents(db: AsyncSession) -> list[tuple[Incident, str, str]]:
    rows = await db.execute(
        select(Incident, HealthRule.name, Host.name)
        .join(HealthRule, HealthRule.id == Incident.rule_id)
        .join(Host, Host.id == Incident.host_id)
        .where(Incident.status == IncidentStatus.OPEN)
        .order_by(Incident.opened_at, Incident.id)
    )
    return [(incident, rule, host) for incident, rule, host in rows.all()]


async def _capacity_sentence(db: AsyncSession) -> str:
    now = await capacity(db)
    running = say_count(now.running, "agent run").capitalize()
    return (
        f"{running} active out of {now.max_running} allowed, "
        f"and {now.free_percent:.0f} percent of memory is free"
    )


async def health(db: AsyncSession, clock: Clock) -> str:
    hosts = await _hosts(db)
    if not hosts:
        return speakable(f"No machines are registered yet. {await _capacity_sentence(db)}.")

    parts: list[str] = [await _capacity_sentence(db)]
    problems = [host for host in hosts if host.status is not HostStatus.UP]
    if not problems:
        parts.append("All machines are up")
    else:
        parts.extend(
            _HOST_SENTENCES[host.status].format(name=clean(host.name)) for host in problems[:LISTED]
        )
        up = len(hosts) - len(problems)
        if up:
            parts.append(f"{say_count(up, 'other machine')} up")

    incidents = await _open_incidents(db)
    if not incidents:
        parts.append("No incidents are open")
    else:
        parts.append(f"{say_count(len(incidents), 'incident').capitalize()} open")
        for incident, rule_name, host_name in incidents[:LISTED]:
            age = say_ago(clock.now() - incident.opened_at)
            parts.append(f"{clean(rule_name)} on {clean(host_name)}, opened {age}")
        if len(incidents) > LISTED:
            parts.append(f"{len(incidents) - LISTED} more incidents are open")

    for host_name, sample in (await _latest_samples(db, await _watched_metrics(db)))[: LISTED * 3]:
        parts.append(
            f"On {clean(host_name)}, {_say_metric(sample.metric, sample.subject, sample.value)}"
        )
    return speakable(join_sentences(parts))
