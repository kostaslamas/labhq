"""A remote host is collected over a real SSH connection, with its host key checked."""

from collections.abc import Iterator
from pathlib import Path

import asyncssh
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.enums import HostStatus
from labhq.db.models import HealthSample, Host, Notification
from labhq.health.collectors import SshCollector
from labhq.health.collectors.remote import connect_with
from labhq.health.monitor import HealthMonitor
from labhq.health.settings import HealthSettings
from labhq.health.ssh import (
    HostKeyNotTrustedError,
    SshSettings,
    SshTarget,
    fetch_host_key,
    fingerprint,
    ssh_runner,
    trust_host_key,
    trusted_keys,
)
from tests.health.sshd import FakeSshd, running_sshd
from tests.health.world import add_remote_host, kinds, open_sessions


@pytest.fixture
def sshd() -> Iterator[FakeSshd]:
    with running_sshd() as server:
        yield server


async def trusted(sshd: FakeSshd, tmp_path: Path) -> SshSettings:
    """Trust the server's key the way `labhq hosts add` does: fetch, compare, record."""
    settings = sshd.client_settings(tmp_path)
    key = await fetch_host_key(sshd.target, settings)
    assert fingerprint(key) == fingerprint(sshd.host_key)
    trust_host_key(settings.known_hosts(), sshd.target, key)
    return settings


def monitor(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, settings: SshSettings
) -> HealthMonitor:
    collector = SshCollector(connect=connect_with(settings))
    return HealthMonitor(
        sessions, clock, HealthSettings(local_host_name="labhq-box"), kinds=kinds(collector)
    )


async def test_a_remote_host_is_collected_over_ssh_as_its_read_only_user(
    database_url: str, clock: FakeClock, sshd: FakeSshd, tmp_path: Path
) -> None:
    settings = await trusted(sshd, tmp_path)
    async with open_sessions(database_url) as sessions:
        host = await add_remote_host(sessions, clock, address=f"127.0.0.1:{sshd.port}")
        await monitor(sessions, clock, settings).tick()
        async with sessions() as db:
            samples = (
                await db.scalars(select(HealthSample).where(HealthSample.host_id == host.id))
            ).all()
            status = (await db.get_one(Host, host.id)).status

    seen = {(sample.metric, sample.subject): sample.value for sample in samples}
    assert seen[("cpu.percent", None)] == 30.0
    assert seen[("memory.percent", None)] == 75.0
    assert seen[("disk.percent", "/")] == 91.0
    assert seen[("service.active", "nginx")] == 0.0
    assert seen[("journal.errors", None)] == 3.0
    assert {sample.sampled_at for sample in samples} == {clock.now()}
    assert status == HostStatus.UP
    # Every command ran as the read-only user; none as the intervention user.
    assert sshd.commands
    assert {user for user, _ in sshd.commands} == {"labhq-ro"}


async def test_a_changed_host_key_fails_the_collection_and_is_reported(
    database_url: str, clock: FakeClock, sshd: FakeSshd, tmp_path: Path
) -> None:
    settings = await trusted(sshd, tmp_path)
    recorded = settings.known_hosts().read_text()
    sshd.change_host_key()

    async with open_sessions(database_url) as sessions:
        host = await add_remote_host(sessions, clock, address=f"127.0.0.1:{sshd.port}")
        await monitor(sessions, clock, settings).tick()
        clock.advance(300)
        await monitor(sessions, clock, settings).tick()
        async with sessions() as db:
            samples = (
                await db.scalars(select(HealthSample).where(HealthSample.host_id == host.id))
            ).all()
            status = (await db.get_one(Host, host.id)).status
            notifications = (await db.scalars(select(Notification))).all()

    assert samples == []
    assert sshd.commands == []
    assert status == HostStatus.DOWN
    # One report per host and day, however often the collection fails meanwhile.
    assert [(n.kind, n.subject) for n in notifications] == [
        ("host_key_rejected", f"host:{host.id}")
    ]
    assert "does not match" in notifications[0].body
    # Nothing was accepted silently: the trusted key is still the only one on record.
    assert settings.known_hosts().read_text() == recorded


async def test_a_host_never_added_is_not_contacted(sshd: FakeSshd, tmp_path: Path) -> None:
    settings = sshd.client_settings(tmp_path)
    with pytest.raises(HostKeyNotTrustedError, match="labhq hosts add"):
        async with ssh_runner(sshd.target, "labhq-ro", settings):
            pass
    assert sshd.commands == []


async def test_trusting_a_new_key_replaces_the_old_one_for_that_target(tmp_path: Path) -> None:
    path = tmp_path / "known_hosts"
    target, other = SshTarget("10.0.0.5", 2222), SshTarget("10.0.0.6")
    old, new, kept = (asyncssh.generate_private_key("ssh-ed25519") for _ in range(3))
    trust_host_key(path, target, old)
    trust_host_key(path, other, kept)
    trust_host_key(path, target, new)

    assert [fingerprint(key) for key in trusted_keys(path, target)] == [fingerprint(new)]
    assert [fingerprint(key) for key in trusted_keys(path, other)] == [fingerprint(kept)]
    assert path.read_text().splitlines()[0].startswith("10.0.0.6 ssh-ed25519 ")
    assert SshTarget.parse("[::1]:2200") == SshTarget("::1", 2200)
    assert SshTarget.parse("nas.lan") == SshTarget("nas.lan", 22)
