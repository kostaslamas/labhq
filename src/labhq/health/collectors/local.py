"""The `local` kind: psutil for the basics, read-only subprocesses for the rest."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from labhq.health.collector import PROBES, Probe, Reading, read_local_metrics
from labhq.health.collectors.commands import (
    CommandProbe,
    CommandRunner,
    LocalRunner,
    ProbeContext,
    run_probes,
)
from labhq.health.collectors.registry import HostTarget
from labhq.health.collectors.system import SYSTEM_PROBES


@dataclass(frozen=True)
class LocalCollector:
    probes: tuple[Probe, ...] = PROBES
    commands: Sequence[CommandProbe] = SYSTEM_PROBES
    runner: CommandRunner = field(default_factory=LocalRunner)

    async def read(self, host: HostTarget, context: ProbeContext) -> list[Reading]:
        readings = read_local_metrics(self.probes)
        readings.extend(await run_probes(self.runner, self.commands, context))
        return readings
