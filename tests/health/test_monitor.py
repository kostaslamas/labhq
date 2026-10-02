"""The loop samples on the interval from settings and evaluates rules after each sample."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import HealthSample, Incident
from labhq.health.monitor import HealthMonitor
from labhq.health.settings import HealthSettings
from tests.health.factories import StubPsutil, add_rule


async def test_monitor_samples_every_interval_and_opens_incidents(
    database_url: str, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    engine = create_engine(database_url)
    sessions = session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            params = {"metric": "disk.percent", "comparison": ">", "value": 90}
            await add_rule(session, clock, params=params)
        start = clock.now()
        settings = HealthSettings(sample_interval_seconds=120, local_host_name="box")

        await HealthMonitor(sessions, clock, settings).run(iterations=3)

        async with sessions() as session:
            times = (await session.scalars(select(HealthSample.sampled_at).distinct())).all()
            incidents = (await session.scalars(select(Incident))).all()
        assert sorted(times) == [start + timedelta(seconds=120 * i) for i in range(3)]
        assert len(incidents) == 1
    finally:
        await engine.dispose()


def test_interval_and_host_name_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LABHQ_HEALTH_SAMPLE_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("LABHQ_HEALTH_LOCAL_HOST_NAME", "homelab")
    settings = HealthSettings()
    assert (settings.sample_interval_seconds, settings.local_host_name) == (60.0, "homelab")
