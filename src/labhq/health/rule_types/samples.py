"""Sample queries the rule types share: subjects of a metric, latest values and windows."""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, select

from labhq.db.models import HealthSample
from labhq.health.rules import RuleContext

# Details key for a sample without a subject.
NO_SUBJECT = ""


def same_subject(subject: str | None) -> ColumnElement[bool]:
    column = HealthSample.subject
    return column.is_(None) if subject is None else column == subject


def _scope(context: RuleContext, metric: str) -> tuple[ColumnElement[bool], ...]:
    return (
        HealthSample.host_id == context.host.id,
        HealthSample.metric == metric,
        HealthSample.sampled_at <= context.now,
    )


async def subjects(context: RuleContext, metric: str, subject: str | None) -> list[str | None]:
    """The named subject, or every subject the host has samples of for `metric`."""
    if subject is not None:
        return [subject]
    rows = await context.session.scalars(
        select(HealthSample.subject).where(*_scope(context, metric)).distinct()
    )
    return list(rows)


async def latest(context: RuleContext, metric: str, subject: str | None) -> dict[str, float]:
    """The latest value of `metric` per subject, keyed by subject (`NO_SUBJECT` for none)."""
    values = {}
    for each in await subjects(context, metric, subject):
        value = await context.session.scalar(
            select(HealthSample.value)
            .where(*_scope(context, metric), same_subject(each))
            .order_by(HealthSample.sampled_at.desc(), HealthSample.id.desc())
            .limit(1)
        )
        if value is not None:
            values[each or NO_SUBJECT] = value
    return values


async def window(
    context: RuleContext, metric: str, subject: str | None, seconds: float
) -> list[tuple[datetime, float]]:
    """The samples of one subject in (now - seconds, now], oldest first."""
    start = context.now - timedelta(seconds=seconds)
    rows = await context.session.execute(
        select(HealthSample.sampled_at, HealthSample.value)
        .where(*_scope(context, metric), same_subject(subject), HealthSample.sampled_at > start)
        .order_by(HealthSample.sampled_at, HealthSample.id)
    )
    return [(at, value) for at, value in rows]
