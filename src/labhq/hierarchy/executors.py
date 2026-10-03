"""`create_agent` and `create_team`: what the engine does once a human approved them.

Importing this module registers both executors, and the light `create_agent` action type, in
the `labhq.approvals` registries. An executor runs in a worker thread with only the payload,
so it opens its own connection to the configured database and runs to completion there.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals import ActionType, Executor, Payload, default_actions, default_executors
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus, RiskClass
from labhq.db.models import Agent
from labhq.hierarchy.roles import HierarchyError
from labhq.hierarchy.settings import HierarchySettings
from labhq.hierarchy.team import TeamProposal, create_team
from labhq.settings import Settings

CREATE_AGENT = "create_agent"
CREATE_TEAM = "create_team"


class AgentApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int


def configured_database_url() -> str:
    # Read on every execution, not cached, like the CLI: one process may serve several setups.
    return Settings().resolved_database_url


@dataclass(frozen=True)
class EngineAccess:
    """How an executor reaches the database, the clock and the settings."""

    database_url: Callable[[], str] = configured_database_url
    clock: Clock = field(default_factory=SystemClock)
    settings: Callable[[], HierarchySettings] = HierarchySettings

    def run[T](self, work: Callable[[AsyncSession], Awaitable[T]]) -> T:
        """Run `work` in one transaction; called from the approval service's worker thread."""

        async def main() -> T:
            engine = create_engine(self.database_url())
            try:
                async with session_factory(engine)() as db:
                    result = await work(db)
                    await db.commit()
                    return result
            finally:
                await engine.dispose()

        return asyncio.run(main())


def agent_executor(access: EngineAccess) -> Executor:
    def run(payload: Payload) -> dict[str, Any]:
        request = AgentApproval.model_validate(payload)

        async def activate(db: AsyncSession) -> dict[str, Any]:
            agent = await db.get(Agent, request.agent_id)
            if agent is None:
                raise HierarchyError(f"no agent {request.agent_id}")
            if agent.status is not AgentStatus.PENDING_APPROVAL:
                raise HierarchyError(f"agent {agent.id} is {agent.status}, not pending approval")
            agent.status = AgentStatus.ACTIVE
            agent.updated_at = access.clock.now()
            return {"agent_id": agent.id, "status": AgentStatus.ACTIVE.value}

        return access.run(activate)

    return Executor(run=run, validate=AgentApproval.model_validate)


def team_executor(access: EngineAccess) -> Executor:
    def run(payload: Payload) -> dict[str, Any]:
        proposal = TeamProposal.model_validate(payload)

        async def create(db: AsyncSession) -> dict[str, Any]:
            agents = await create_team(db, access.clock, proposal, access.settings())
            return {"manager_id": proposal.manager_id, "agents": agents}

        return access.run(create)

    return Executor(run=run, validate=TeamProposal.model_validate)


# Plan §5, rule 4: approving one new agent is light; a whole team stays heavy.
default_actions.register(CREATE_AGENT, ActionType(CREATE_AGENT, RiskClass.LIGHT))
default_executors.register(CREATE_AGENT, agent_executor(EngineAccess()))
default_executors.register(CREATE_TEAM, team_executor(EngineAccess()))
