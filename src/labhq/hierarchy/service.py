"""The CEO, its managers and their teams (plan §2): every caller goes through `Hierarchy`.

Nothing here decides an approval. New agents wait for a human (plan §5, rule 4) and a team
waits for a heavy approval, which a voice confirmation can never give (rule 7).
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import UnknownAdapterError
from labhq.adapters.kinds import AgentChoice, choice_named
from labhq.approvals import ApprovalService
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, ApprovalStatus
from labhq.db.models import Agent, Approval
from labhq.hierarchy.executors import CREATE_AGENT, CREATE_TEAM
from labhq.hierarchy.roles import CEO, MANAGER, HierarchyError, check_reports_to
from labhq.hierarchy.settings import HierarchySettings
from labhq.hierarchy.team import (
    ProposedMember,
    TeamProposal,
    check_adapters,
    check_team_size,
    find_manager,
)
from labhq.usage.plan import FALLBACK_ADAPTER_KEY, FALLBACK_KEY
from labhq.work import find_project

CEO_TITLE = "CEO"


@dataclass(frozen=True)
class ManagerAssignment:
    manager: Agent
    # None when new-agent approval is switched off and the manager starts active.
    approval: Approval | None


@dataclass
class Node:
    agent: Agent
    reports: list["Node"] = field(default_factory=list)


class Hierarchy:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        adapters: Collection[str],
        approvals: ApprovalService | None = None,
        settings: HierarchySettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._adapters = adapters
        self._approvals = approvals or ApprovalService(sessions, clock=clock)
        self._settings = settings or HierarchySettings()

    def _adapter(self, adapter: str | None) -> str:
        chosen = adapter or self._settings.org_adapter
        if chosen not in self._adapters:
            raise UnknownAdapterError(f"no adapter registered as {chosen!r}")
        return chosen

    async def ensure_ceo(self, adapter: str | None = None) -> Agent:
        """The CEO, created on first use. The operator asks for it, so it starts active."""
        async with self._sessions() as db:
            ceo = await _current_ceo(db)
            if ceo is not None:
                return ceo
            now = self._clock.now()
            ceo = Agent(
                project_id=None,
                role=CEO,
                title=CEO_TITLE,
                reports_to=None,
                adapter=self._adapter(adapter),
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            db.add(ceo)
            await db.commit()
        return ceo

    async def current_ceo(self) -> Agent | None:
        async with self._sessions() as db:
            return await _current_ceo(db)

    async def configure_ceo(self, primary: str, backup: str | None) -> Agent:
        """Set the agent kinds of the one CEO shared by every project."""
        if backup == primary:
            raise HierarchyError("the CEO's backup must differ from its primary agent")
        first = self._available_choice(primary)
        second = self._available_choice(backup) if backup is not None else None
        async with self._sessions() as db:
            ceo = await _current_ceo(db)
            now = self._clock.now()
            if ceo is None:
                ceo = Agent(
                    project_id=None,
                    role=CEO,
                    title=CEO_TITLE,
                    reports_to=None,
                    status=AgentStatus.ACTIVE,
                    created_at=now,
                )
                db.add(ceo)
            config = dict(ceo.config or {})
            for key in ("agent", FALLBACK_KEY, FALLBACK_ADAPTER_KEY):
                config.pop(key, None)
            config.update(first.config)
            if second is not None:
                config[FALLBACK_KEY] = second.name
                config[FALLBACK_ADAPTER_KEY] = second.adapter
            ceo.adapter = first.adapter
            ceo.config = config
            ceo.updated_at = now
            await db.commit()
        return ceo

    def _available_choice(self, name: str) -> AgentChoice:
        choice = choice_named(name)
        if choice.adapter not in self._adapters:
            raise HierarchyError(f"agent kind {name!r} cannot run on this server")
        if choice.found() is None:
            raise HierarchyError(f"agent kind {name!r} is not installed on this server")
        return choice

    async def assign_manager(
        self, project: str, *, adapter: str | None = None, title: str | None = None
    ) -> ManagerAssignment:
        """Give a project without a manager its manager, reporting to the CEO."""
        ceo = await self.ensure_ceo()
        check_reports_to(MANAGER, ceo.role)
        pending = self._settings.approve_new_agents
        async with self._sessions() as db:
            owner = await find_project(db, project)
            await self._release_refused_manager(db, owner.id)
            now = self._clock.now()
            manager = Agent(
                project_id=owner.id,
                role=MANAGER,
                title=title or f"{owner.name} manager",
                reports_to=ceo.id,
                adapter=self._adapter(adapter),
                status=AgentStatus.PENDING_APPROVAL if pending else AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            db.add(manager)
            await db.commit()
        if not pending:
            return ManagerAssignment(manager, None)
        approval = await self._approvals.request(
            CREATE_AGENT, {"agent_id": manager.id}, agent_id=ceo.id
        )
        return ManagerAssignment(manager, approval)

    async def _release_refused_manager(self, db: AsyncSession, project_id: int) -> None:
        """Refuse a second manager, unless the first never got and can no longer get approval."""
        query = select(Agent).where(
            Agent.project_id == project_id,
            Agent.role == MANAGER,
            Agent.status != AgentStatus.RETIRED,
        )
        for existing in await db.scalars(query):
            waiting = existing.status is AgentStatus.PENDING_APPROVAL
            if not waiting or await _awaits_approval(db, existing.id):
                raise HierarchyError(
                    f"project {project_id} already has manager {existing.id} ({existing.status})"
                )
            # Its approval was rejected or failed: retire it so the project can have one.
            existing.status = AgentStatus.RETIRED
            existing.updated_at = self._clock.now()

    async def propose_team(
        self, manager_id: int, members: Iterable[ProposedMember | Mapping[str, Any]]
    ) -> Approval:
        """Record one heavy `create_team` approval; no agent exists until it is approved."""
        proposal = TeamProposal.model_validate(
            {"manager_id": manager_id, "members": tuple(members)}
        )
        check_adapters(proposal, self._adapters)
        async with self._sessions() as db:
            manager = await find_manager(db, manager_id)
            await check_team_size(db, manager, len(proposal.members), self._settings)
        return await self._approvals.request(
            CREATE_TEAM, proposal.model_dump(mode="json"), agent_id=manager_id
        )

    async def tree(self) -> list[Node]:
        """Every agent that is not retired, under the agent it reports to."""
        query = select(Agent).where(Agent.status != AgentStatus.RETIRED).order_by(Agent.id)
        async with self._sessions() as db:
            agents = list(await db.scalars(query))
        nodes = {agent.id: Node(agent) for agent in agents}
        roots: list[Node] = []
        for agent in agents:
            parent = nodes.get(agent.reports_to) if agent.reports_to is not None else None
            (parent.reports if parent else roots).append(nodes[agent.id])
        return roots


async def _current_ceo(db: AsyncSession) -> Agent | None:
    query = (
        select(Agent)
        .where(Agent.role == CEO, Agent.status != AgentStatus.RETIRED)
        .order_by(Agent.id)
        .limit(1)
    )
    return await db.scalar(query)


async def _awaits_approval(db: AsyncSession, agent_id: int) -> bool:
    query = select(Approval).where(
        Approval.type == CREATE_AGENT, Approval.status == ApprovalStatus.PENDING
    )
    return any(approval.payload.get("agent_id") == agent_id for approval in await db.scalars(query))
