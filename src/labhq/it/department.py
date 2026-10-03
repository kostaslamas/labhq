"""One pass of the IT department: wake its agent for new tickets and for the daily report.

The always-on program runs a pass on the health loop's interval, so a ticket reaches the
agent within one collection interval of the incident that opened it. Without an active IT
agent a pass does nothing; open incidents are found again once there is one.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.it.agent import find_it_agent
from labhq.it.settings import ItSettings
from labhq.it.wakeups import wake_for_incidents, wake_for_report
from labhq.scheduler import EnqueueResult


@dataclass(frozen=True)
class ItPass:
    agent_id: int | None
    incidents: list[EnqueueResult] = field(default_factory=list)
    report: EnqueueResult | None = None


@dataclass
class ItDepartment:
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    settings: ItSettings = field(default_factory=ItSettings)

    async def tick(self) -> ItPass:
        async with self.sessions() as db, db.begin():
            agent = await find_it_agent(db)
            if agent is None or agent.status is not AgentStatus.ACTIVE:
                return ItPass(agent.id if agent is not None else None)
            incidents = await wake_for_incidents(db, self.clock, agent, self.settings)
            report = await wake_for_report(db, self.clock, agent, self.settings)
        return ItPass(agent.id, incidents, report)


class _ProgramContext(Protocol):
    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]: ...

    @property
    def clock(self) -> Clock: ...


class _ProgramServices(Protocol):
    @property
    def context(self) -> _ProgramContext: ...


def it_step(services: _ProgramServices) -> Callable[[], Awaitable[object]]:
    """The always-on program's `it` loop: one pass per tick, paced by the program."""
    context = services.context
    return ItDepartment(context.sessions, context.clock).tick
