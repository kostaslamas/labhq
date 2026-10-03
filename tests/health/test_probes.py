"""Each probe turns a captured command output into its named metrics, on every host kind."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from labhq.health.collector import Reading
from labhq.health.collectors import (
    CommandProbe,
    CommandResult,
    HostTarget,
    LocalCollector,
    ProbeContext,
    SshCollector,
)
from labhq.health.collectors.procfs import PROCFS_PROBES
from labhq.health.collectors.system import SYSTEM_PROBES
from labhq.health.ssh import SshTarget
from tests.health.stubs import StubRunner, StubSsh, captured, fixture

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
CONTEXT = ProbeContext(
    now=NOW,
    since=NOW - timedelta(seconds=300),
    certificates=("example.com:443", "/etc/ssl/certs/internal.pem", "unreachable.example:443"),
)
PROBES = {probe.name: probe for probe in (*PROCFS_PROBES, *SYSTEM_PROBES)}
LOCAL = HostTarget(1, "labhq-box", is_local=True)
REMOTE = HostTarget(2, "nas", is_local=False, address="10.0.0.5:2222", ssh_user="labhq-ro")

EXPECTED: dict[str, set[Reading]] = {
    "services": {
        Reading("service.active", 1.0, "cron"),
        Reading("service.active", 0.0, "nginx"),
        Reading("service.active", 1.0, "ssh"),
        Reading("service.active", 1.0, "systemd-journald"),
    },
    "containers": {
        Reading("container.running", 1.0, "web"),
        Reading("container.running", 0.0, "worker"),
        Reading("container.running", 1.0, "db"),
    },
    # The device smartctl could not open has no verdict and is left out.
    "smart": {Reading("smart.healthy", 1.0, "/dev/sda"), Reading("smart.healthy", 0.0, "/dev/sdb")},
    "journal": {Reading("journal.errors", 3.0)},
    # The unreachable endpoint costs only its own certificate.
    "certificates": {
        Reading("cert.days_left", 10.0, "example.com:443"),
        Reading("cert.days_left", 91.0, "/etc/ssl/certs/internal.pem"),
    },
    "updates": {Reading("updates.pending", 3.0)},
    "cpu": {Reading("cpu.percent", 30.0)},
    "memory": {
        Reading("memory.percent", 75.0),
        Reading("memory.available_bytes", 2_000_000 * 1024.0),
    },
    "load": {Reading("load.1m", 0.52), Reading("load.5m", 0.41), Reading("load.15m", 0.30)},
    # tmpfs and overlay are not disks; a mount point keeps its spaces.
    "disks": {Reading("disk.percent", 91.0, "/"), Reading("disk.percent", 25.0, "/srv/data dir")},
}


def test_every_probe_has_a_fixture_case() -> None:
    assert set(EXPECTED) == set(PROBES)


async def read_locally(probe: CommandProbe, runner: StubRunner) -> set[Reading]:
    collector = LocalCollector(probes=(), commands=(probe,), runner=runner)
    return set(await collector.read(LOCAL, CONTEXT))


async def read_over_ssh(probe: CommandProbe, runner: StubRunner) -> set[Reading]:
    ssh = StubSsh(runner)
    readings = set(await SshCollector(connect=ssh, probes=(probe,)).read(REMOTE, CONTEXT))
    assert ssh.logins == [(SshTarget("10.0.0.5", 2222), "labhq-ro")]
    return readings


type Read = Callable[[CommandProbe, StubRunner], Awaitable[set[Reading]]]


@pytest.mark.parametrize("read", [read_locally, read_over_ssh], ids=["local", "ssh"])
@pytest.mark.parametrize("name", sorted(EXPECTED))
async def test_a_probe_parses_its_captured_output(read: Read, name: str) -> None:
    assert await read(PROBES[name], StubRunner()) == EXPECTED[name]


async def test_dnf_counts_updates_without_the_obsoletes_section() -> None:
    runner = StubRunner(captured({"apt list": CommandResult(0, fixture("dnf_check_update.txt"))}))
    assert await read_locally(PROBES["updates"], runner) == {Reading("updates.pending", 2.0)}


async def test_the_journal_is_read_from_the_previous_sample_up_to_now() -> None:
    runner = StubRunner()
    await read_locally(PROBES["journal"], runner)
    since, until = int(CONTEXT.since.timestamp()), int(NOW.timestamp()) - 1
    assert f"--since=@{since}" in runner.commands[0]
    assert f"--until=@{until}" in runner.commands[0]


async def test_no_certificates_to_watch_runs_no_command() -> None:
    runner = StubRunner()
    collector = LocalCollector(probes=(), commands=(PROBES["certificates"],), runner=runner)
    context = ProbeContext(now=NOW, since=CONTEXT.since)
    assert await collector.read(LOCAL, context) == []
    assert runner.commands == []


async def test_certificate_targets_are_arguments_never_shell_text() -> None:
    runner = StubRunner()
    hostile = "/tmp/x.pem; rm -rf /"
    context = ProbeContext(now=NOW, since=CONTEXT.since, certificates=(hostile,))
    await read_over_ssh(PROBES["certificates"], runner)
    await LocalCollector(probes=(), commands=(PROBES["certificates"],), runner=runner).read(
        LOCAL, context
    )
    assert runner.commands[-1][-1] == hostile
    assert hostile not in runner.commands[-1][2]


@pytest.mark.parametrize(
    "result",
    [CommandResult(127, "", "command not found"), CommandResult(0, "garbage")],
    ids=["missing tool", "unreadable output"],
)
async def test_a_failing_probe_costs_only_its_own_metric(result: CommandResult) -> None:
    runner = StubRunner(captured({"/proc/meminfo": result, "docker ps": result}))
    ssh = StubSsh(runner)
    readings = await SshCollector(connect=ssh).read(REMOTE, CONTEXT)

    metrics = {reading.metric for reading in readings}
    assert not metrics & {"memory.percent", "memory.available_bytes", "container.running"}
    assert {"cpu.percent", "load.1m", "disk.percent", "service.active", "cert.days_left"} <= metrics
