"""The `ssh` kind: every probe runs over one SSH connection as the host's read-only user."""

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field

from labhq.health.collector import Reading
from labhq.health.collectors.commands import CommandProbe, CommandRunner, ProbeContext, run_probes
from labhq.health.collectors.procfs import PROCFS_PROBES
from labhq.health.collectors.registry import HostTarget
from labhq.health.collectors.system import SYSTEM_PROBES
from labhq.health.ssh import SshError, SshSettings, SshTarget, ssh_runner

type Connect = Callable[[SshTarget, str], AbstractAsyncContextManager[CommandRunner]]

REMOTE_PROBES: tuple[CommandProbe, ...] = (*PROCFS_PROBES, *SYSTEM_PROBES)


def connect_with(settings: SshSettings | None = None) -> Connect:
    def connect(target: SshTarget, user: str) -> AbstractAsyncContextManager[CommandRunner]:
        # Settings are read per connection, so a changed key path needs no restart.
        return ssh_runner(target, user, settings or SshSettings())

    return connect


@dataclass(frozen=True)
class SshCollector:
    connect: Connect = field(default_factory=connect_with)
    probes: Sequence[CommandProbe] = REMOTE_PROBES

    async def read(self, host: HostTarget, context: ProbeContext) -> list[Reading]:
        if not host.address or not host.ssh_user:
            raise SshError(f"host {host.name} needs an address and a read-only SSH user")
        async with self.connect(SshTarget.parse(host.address), host.ssh_user) as runner:
            return await run_probes(runner, self.probes, context)
