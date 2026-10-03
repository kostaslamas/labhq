"""Incidents reach the `infra` channel: one post when opened, one when resolved."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import IncidentStatus
from labhq.db.models import HealthRule, Host, Incident
from labhq.meetings.channels.incidents import enqueue_incidents
from tests.meetings.channels.conftest import Bridge


async def _incident(
    sessions: async_sessionmaker[AsyncSession], clock: Clock, *, opened_at: datetime
) -> int:
    now = clock.now()
    async with sessions() as db:
        host = Host(name="nas", created_at=now, updated_at=now)
        rule = HealthRule(
            type="threshold",
            name="Disk almost full",
            params={},
            reason="Backups stop when the disk fills.",
            created_by="owner",
            created_at=now,
            updated_at=now,
        )
        db.add_all([host, rule])
        await db.flush()
        incident = Incident(rule_id=rule.id, host_id=host.id, details={}, opened_at=opened_at)
        db.add(incident)
        await db.commit()
        return incident.id


async def _pass(bridge: Bridge) -> int:
    world = bridge.world
    async with world.sessions() as db:
        await enqueue_incidents(db, world.clock, bridge.settings)
        await db.commit()
    return await bridge.flush()


async def test_an_opened_incident_is_posted_once_to_infra(bridge: Bridge) -> None:
    world = bridge.world
    incident_id = await _incident(world.sessions, world.clock, opened_at=world.clock.now())

    assert await _pass(bridge) == 1
    assert await _pass(bridge) == 0

    assert bridge.channel_names() == ["infra"]
    ((thread_id, posts),) = bridge.service.posts.items()
    assert bridge.service.threads[thread_id] == f"Incident #{incident_id}: Disk almost full on nas"
    assert [(p.persona.name, p.text) for p in posts] == [
        (
            "labhq",
            f"Incident #{incident_id} opened on nas: Disk almost full (rule 1, threshold). "
            "Backups stop when the disk fills.",
        )
    ]


async def test_a_resolved_incident_is_posted_in_the_same_thread(bridge: Bridge) -> None:
    world = bridge.world
    incident_id = await _incident(world.sessions, world.clock, opened_at=world.clock.now())
    await _pass(bridge)
    async with world.sessions() as db:
        incident = await db.get_one(Incident, incident_id)
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = world.clock.now()
        await db.commit()

    assert await _pass(bridge) == 1
    assert await _pass(bridge) == 0

    (posts,) = bridge.service.posts.values()
    assert [p.text for p in posts][
        1
    ] == f"Incident #{incident_id} resolved on nas: Disk almost full."


async def test_an_incident_older_than_the_lookback_is_not_posted(bridge: Bridge) -> None:
    world = bridge.world
    old = world.clock.now() - timedelta(seconds=bridge.settings.incident_lookback_seconds + 60)
    await _incident(world.sessions, world.clock, opened_at=old)

    assert await _pass(bridge) == 0
    assert bridge.service.posts == {}
