"""The loop samples every host on the interval from settings and evaluates rules after each."""

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import HostStatus
from labhq.db.models import HealthSample, Host, Incident
from labhq.health import collectors
from labhq.health.collector import Reading
from labhq.health.collectors import CommandResult, LocalCollector, SshCollector
from labhq.health.collectors.commands import ProbeContext
from labhq.health.collectors.registry import HostTarget
from labhq.health.monitor import HealthMonitor
from labhq.health.settings import HealthSettings
from labhq.health.ssh import SshError
from labhq.program import ProgramSettings, default_loops, run_loop
from labhq.settings import Settings
from tests.health.factories import StubPsutil, add_rule
from tests.health.stubs import StubRunner, StubSsh, captured
from tests.health.world import add_remote_host, kinds, open_sessions
from tests.program.conftest import Passes, SteppedClock

SETTINGS = HealthSettings(sample_interval_seconds=120, local_host_name="box")


async def test_monitor_samples_every_interval_and_opens_incidents(
    database_url: str, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    async with open_sessions(database_url) as sessions:
        async with sessions() as session, session.begin():
            params = {"metric": "disk.percent", "comparison": ">", "value": 90}
            await add_rule(session, clock, params=params)
        start = clock.now()
        monitor = HealthMonitor(
            sessions, clock, SETTINGS, kinds=kinds(SshCollector(connect=StubSsh()))
        )

        await monitor.run(iterations=3)

        async with sessions() as session:
            times = (await session.scalars(select(HealthSample.sampled_at).distinct())).all()
            incidents = (await session.scalars(select(Incident))).all()
    assert sorted(times) == [start + timedelta(seconds=120 * i) for i in range(3)]
    assert len(incidents) == 1


async def test_every_host_is_collected_and_the_rules_see_them_all(
    database_url: str, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    ssh = StubSsh()
    async with open_sessions(database_url) as sessions:
        remote = await add_remote_host(sessions, clock, address="10.0.0.5")
        async with sessions() as session, session.begin():
            params = {"metric": "disk.percent", "comparison": ">", "value": 90}
            await add_rule(session, clock, params=params)

        await HealthMonitor(
            sessions, clock, SETTINGS, kinds=kinds(SshCollector(connect=ssh))
        ).tick()

        async with sessions() as session:
            hosts = {host.name: host for host in (await session.scalars(select(Host))).all()}
            incidents = (await session.scalars(select(Incident))).all()
    assert set(hosts) == {"box", "nas"}
    assert {hosts["box"].status, hosts["nas"].status} == {HostStatus.UP}
    # Local /data at 91% through psutil, remote / at 91% through `df -P`.
    assert {incident.host_id for incident in incidents} == {hosts["box"].id, remote.id}
    assert ssh.logins and ssh.logins[0][1] == "labhq-ro"


async def test_one_failing_probe_leaves_the_hosts_other_metrics_intact(
    database_url: str, clock: FakeClock
) -> None:
    broken = CommandResult(1, "", "Cannot connect to the Docker daemon")
    ssh = StubSsh(StubRunner(captured({"docker ps": broken})))
    async with open_sessions(database_url) as sessions:
        remote = await add_remote_host(sessions, clock, address="10.0.0.5")
        await HealthMonitor(
            sessions, clock, SETTINGS, kinds=kinds(SshCollector(connect=ssh))
        ).tick()
        async with sessions() as session:
            metrics = set(
                await session.scalars(
                    select(HealthSample.metric).where(HealthSample.host_id == remote.id)
                )
            )
    assert "container.running" not in metrics
    assert metrics == {
        "cpu.percent",
        "memory.percent",
        "memory.available_bytes",
        "load.1m",
        "load.5m",
        "load.15m",
        "disk.percent",
        "service.active",
        "smart.healthy",
        "journal.errors",
        "updates.pending",
    }


class Unreachable:
    async def read(self, host: HostTarget, context: ProbeContext) -> list[Reading]:
        raise SshError(f"cannot connect to {host.name}")


async def test_an_unreachable_host_is_down_and_the_others_are_still_collected(
    database_url: str, clock: FakeClock, stub_psutil: StubPsutil
) -> None:
    async with open_sessions(database_url) as sessions:
        remote = await add_remote_host(sessions, clock, address="10.0.0.5")
        await HealthMonitor(sessions, clock, SETTINGS, kinds=kinds(Unreachable())).tick()
        async with sessions() as session:
            status = (await session.get_one(Host, remote.id)).status
            hosts = set(await session.scalars(select(HealthSample.host_id).distinct()))
    assert status == HostStatus.DOWN
    assert remote.id not in hosts and len(hosts) == 1


async def test_the_programs_health_loop_collects_at_its_interval_on_the_fake_clock(
    database_url: str,
    stub_psutil: StubPsutil,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stepped = SteppedClock()
    start = stepped.now()
    # The loop builds its monitor from the default kinds; no real command runs here.
    registry = kinds(SshCollector(connect=StubSsh()), LocalCollector(commands=()))
    monkeypatch.setattr(collectors, "default_collectors", registry)
    [spec] = [spec for spec in default_loops if spec.name == "health"]
    interval = spec.interval(ProgramSettings(health_interval_seconds=60))
    passes = Passes()

    async with open_sessions(database_url) as sessions:
        settings = Settings(data_dir=tmp_path, database_url=database_url)
        services = SimpleNamespace(context=Context(settings, sessions, stepped))
        step = passes.watch(spec.name, spec.build(services))  # type: ignore[arg-type]
        loop = asyncio.create_task(run_loop(spec.name, interval, step, stepped))
        for done in (1, 2, 3):
            await passes.reached(spec.name, done)
            await stepped.tick(30)
            await stepped.tick(30)
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        async with sessions() as session:
            times = sorted(await session.scalars(select(HealthSample.sampled_at).distinct()))
    assert times == [start + timedelta(seconds=60 * i) for i in range(3)]
