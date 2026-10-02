"""The collector's loop: sample, evaluate the rules, commit, wait an interval."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.health.collector import PROBES, Probe, collect_local
from labhq.health.incidents import IncidentChange, evaluate_rules
from labhq.health.rules import RuleRegistry, registry
from labhq.health.settings import HealthSettings


@dataclass
class HealthMonitor:
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    settings: HealthSettings
    rules: RuleRegistry = registry
    probes: tuple[Probe, ...] = PROBES

    async def tick(self) -> list[IncidentChange]:
        async with self.sessions() as session, session.begin():
            await collect_local(session, self.clock, self.settings.local_host_name, self.probes)
            return await evaluate_rules(session, self.clock, self.rules)

    async def run(self, iterations: int | None = None) -> None:
        """Tick every `sample_interval_seconds`; `iterations` bounds the loop for tests."""
        done = 0
        while iterations is None or done < iterations:
            await self.tick()
            done += 1
            await self.clock.sleep(self.settings.sample_interval_seconds)
