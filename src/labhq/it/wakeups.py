"""What wakes the IT agent: an incident's ticket, and one daily report (plan §2.2).

Both go through the scheduler's existing sources. The idempotency key names the incident or
the day, so a pass that runs again, or a second process, never wakes the agent twice.
"""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import HealthRuleAction, IncidentStatus, WakeupSource
from labhq.db.models import Agent, HealthRule, Host, Incident, Task
from labhq.it.settings import ItSettings
from labhq.scheduler import EnqueueResult, Wakeup, enqueue

REPORT_REASON = (
    "Daily IT report: in a few lines, what is healthy, what is not, the open tickets and the "
    "rules you changed since the last report, and why."
)


def incident_key(incident: Incident) -> str:
    return f"incident:{incident.id}:it"


def report_key(agent: Agent, day: str) -> str:
    return f"it:report:agent:{agent.id}:{day}"


def incident_wakeup(agent: Agent, incident: Incident, rule: HealthRule, host: Host) -> Wakeup:
    assert incident.task_id is not None
    return Wakeup(
        agent_id=agent.id,
        source=WakeupSource.ASSIGNMENT,
        idempotency_key=incident_key(incident),
        task_id=incident.task_id,
        reason=f"incident {incident.id} opened on {host.name}: rule {rule.id} {rule.name!r}",
    )


async def wake_for_incidents(
    db: AsyncSession, clock: Clock, agent: Agent, settings: ItSettings
) -> list[EnqueueResult]:
    """Hand each ticket of an open or recent incident to the agent, once per incident."""
    since = clock.now() - timedelta(hours=settings.incident_lookback_hours)
    rows = await db.execute(
        select(Incident, HealthRule, Host)
        .join(HealthRule, HealthRule.id == Incident.rule_id)
        .join(Host, Host.id == Incident.host_id)
        .where(
            HealthRule.action == HealthRuleAction.TICKET,
            Incident.task_id.is_not(None),
            or_(Incident.status == IncidentStatus.OPEN, Incident.opened_at >= since),
        )
        .order_by(Incident.id)
    )
    results = []
    for incident, rule, host in rows:
        task = await db.get_one(Task, incident.task_id)
        if task.assignee_id is None:
            task.assignee_id = agent.id
            task.updated_at = clock.now()
        results.append(await enqueue(db, incident_wakeup(agent, incident, rule, host), clock))
    return results


async def wake_for_report(
    db: AsyncSession, clock: Clock, agent: Agent, settings: ItSettings
) -> EnqueueResult | None:
    """The day's report, once its local time has come; None before then."""
    local = clock.now().astimezone(settings.zone)
    if local.time() < settings.report_time:
        return None
    wakeup = Wakeup(
        agent_id=agent.id,
        source=WakeupSource.TIMER,
        idempotency_key=report_key(agent, local.date().isoformat()),
        reason=REPORT_REASON,
    )
    return await enqueue(db, wakeup, clock)
