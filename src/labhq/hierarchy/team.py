"""A manager's team: the proposal a human approves, its size cap and its creation."""

from collections.abc import Collection
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters import UnknownAdapterError
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent
from labhq.hierarchy.roles import HEAD, MANAGER, HierarchyError, check_reports_to
from labhq.hierarchy.settings import HierarchySettings

# A manager's `config` key that overrides the `max_team_size` setting for its team.
TEAM_SIZE_KEY = "max_team_size"
# The roles that lead a team: a project's manager, a department's head.
TEAM_LEADERS = frozenset({MANAGER, HEAD})
# `agents.config` key holding a department's kind, name and folder, for the agent's prompt.
DEPARTMENT_KEY = "department"


class TeamSizeError(HierarchyError):
    pass


class ProposedMember(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Names the member inside the proposal, so others can report to it before it has an id.
    key: str = Field(min_length=1, max_length=64)
    role: str
    title: str = Field(min_length=1, max_length=200)
    adapter: str = Field(min_length=1, max_length=64)
    # Another member's key; None reports to the proposing manager.
    reports_to: str | None = None


class TeamProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manager_id: int
    # The role of the agent the members report to: a manager, or a department head.
    root_role: str = MANAGER
    members: tuple[ProposedMember, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _reporting_lines(self) -> Self:
        roles: dict[str, str] = {}
        for member in self.members:
            if member.key in roles:
                raise ValueError(f"member key {member.key!r} is proposed twice")
            roles[member.key] = member.role
        for member in self.members:
            if member.reports_to is not None and member.reports_to not in roles:
                raise ValueError(f"{member.key!r} reports to {member.reports_to!r}, not proposed")
            parent = self.root_role if member.reports_to is None else roles[member.reports_to]
            check_reports_to(member.role, parent)
        return self

    def in_creation_order(self) -> list[ProposedMember]:
        """Members after the member they report to, so every parent has an id first."""
        ordered: list[ProposedMember] = []
        placed: set[str | None] = {None}
        waiting = list(self.members)
        while waiting:
            ready = [member for member in waiting if member.reports_to in placed]
            if not ready:
                raise ValueError("the proposal's reporting lines form a cycle")
            ordered.extend(ready)
            placed.update(member.key for member in ready)
            waiting = [member for member in waiting if member.key not in placed]
        return ordered


def check_adapters(proposal: TeamProposal, adapters: Collection[str]) -> None:
    for member in proposal.members:
        if member.adapter not in adapters:
            raise UnknownAdapterError(f"no adapter registered as {member.adapter!r}")


async def find_manager(db: AsyncSession, manager_id: int) -> Agent:
    manager = await db.get(Agent, manager_id)
    if manager is None or manager.role not in TEAM_LEADERS:
        raise HierarchyError(f"agent {manager_id} is not a manager or a department head")
    if manager.status is not AgentStatus.ACTIVE:
        raise HierarchyError(f"manager {manager_id} is {manager.status}, not active")
    return manager


async def team_of(db: AsyncSession, manager: Agent) -> list[Agent]:
    """Every agent under `manager`, directly or through a lead; retired agents left out."""
    scope = (
        Agent.department_id == manager.department_id
        if manager.department_id is not None
        else Agent.project_id == manager.project_id
    )
    query = select(Agent).where(scope, Agent.status != AgentStatus.RETIRED)
    reports: dict[int | None, list[Agent]] = {}
    for agent in await db.scalars(query):
        reports.setdefault(agent.reports_to, []).append(agent)
    team: list[Agent] = []
    frontier = [manager.id]
    while frontier:
        below = [agent for parent in frontier for agent in reports.get(parent, [])]
        team.extend(below)
        frontier = [agent.id for agent in below]
    return team


def team_size_cap(manager: Agent, settings: HierarchySettings) -> int:
    cap = manager.config.get(TEAM_SIZE_KEY, settings.max_team_size)
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise HierarchyError(f"manager {manager.id} has an invalid {TEAM_SIZE_KEY}: {cap!r}")
    return cap


async def check_team_size(
    db: AsyncSession, manager: Agent, adding: int, settings: HierarchySettings
) -> None:
    current = len(await team_of(db, manager))
    cap = team_size_cap(manager, settings)
    if current + adding > cap:
        raise TeamSizeError(
            f"manager {manager.id} has {current} agents; adding {adding} would pass "
            f"its team-size cap of {cap}"
        )


def member_config(manager: Agent) -> dict[str, object]:
    """What a team member inherits from its leader: the department it works in."""
    return {key: manager.config[key] for key in (DEPARTMENT_KEY, "tools") if key in manager.config}


async def create_team(
    db: AsyncSession, clock: Clock, proposal: TeamProposal, settings: HierarchySettings
) -> dict[str, int]:
    """Create the approved team, active, after checking the cap again: the team may have grown."""
    manager = await find_manager(db, proposal.manager_id)
    await check_team_size(db, manager, len(proposal.members), settings)
    ids: dict[str | None, int] = {None: manager.id}
    now = clock.now()
    for member in proposal.in_creation_order():
        agent = Agent(
            project_id=manager.project_id,
            department_id=manager.department_id,
            role=member.role,
            title=member.title,
            reports_to=ids[member.reports_to],
            adapter=member.adapter,
            config=member_config(manager),
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.flush()
        ids[member.key] = agent.id
    return {key: agent_id for key, agent_id in ids.items() if key is not None}
