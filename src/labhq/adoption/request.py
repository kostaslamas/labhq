"""Ask to adopt a running agent: a light `adopt_agent` approval, and nothing moves yet.

The owner names the process, or the CEO proposes one from discovery. Adoption ends a
process the owner started, so it waits for the owner's confirmation; it is light because the
conversation is kept (ADR 0005).
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.adoption.checkout import is_git_repository, toplevel
from labhq.adoption.discovery import Processes, RunningAgent, all_processes, discover, find_running
from labhq.adoption.observe import AdoptionError, OwnerTmux
from labhq.adoption.saved import find_saved_session
from labhq.adoption.settings import AdoptionSettings, get_adoption_settings
from labhq.approvals import ApprovalService
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Approval, Project
from labhq.hierarchy import MANAGER, HierarchyError

ADOPT_AGENT = "adopt_agent"
ADOPT_SAVED_SESSION = "adopt_saved_session"
NO_ISOLATION_WARNING = (
    "No sandbox is configured (LABHQ_ADOPT_SANDBOX) and the agent cannot run as a separate OS "
    "user, because its conversation is stored under your home. It will run as you, in your "
    "project folder: labhq's environment and hook deter a push but do not prevent one "
    "(plan §5, rule 6)."
)


class AdoptPayload(BaseModel):
    """What the owner approves: one process, its directory and the project it will manage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    pid: int = Field(gt=0)
    started_at: float
    cwd: str
    project: str = Field(min_length=1)
    # The owner's tmux pane the agent runs in; None outside tmux.
    pane: str | None = None
    warnings: tuple[str, ...] = ()


class SavedSessionPayload(BaseModel):
    """A chosen, stopped conversation to continue as the project's manager."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    session_id: str
    cwd: str
    project: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdoptionRequest:
    approval: Approval
    agent: RunningAgent
    warnings: tuple[str, ...]


def isolation_warnings(settings: AdoptionSettings) -> tuple[str, ...]:
    return () if settings.sandbox else (NO_ISOLATION_WARNING,)


async def manager_of(db: AsyncSession, project_name: str) -> Agent | None:
    query = (
        select(Agent)
        .join(Project, Project.id == Agent.project_id)
        .where(
            Project.name == project_name,
            Agent.role == MANAGER,
            Agent.status != AgentStatus.RETIRED,
        )
    )
    return await db.scalar(query.limit(1))


async def refuse_second_manager(db: AsyncSession, project_name: str) -> None:
    existing = await manager_of(db, project_name)
    if existing is not None:
        raise HierarchyError(
            f"project {project_name!r} already has manager {existing.id} ({existing.status})"
        )


def works_on_project(cwd: Path, project_path: Path) -> bool:
    """An adopted manager must continue in the project it is assigned to."""
    root = project_path.resolve()
    if is_git_repository(cwd):
        return toplevel(cwd).resolve() == root
    return cwd.resolve().is_relative_to(root)


class Adoptions:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        approvals: ApprovalService | None = None,
        kinds: AgentKinds = default_kinds,
        settings: AdoptionSettings | None = None,
        processes: Processes = all_processes,
    ) -> None:
        self._sessions = sessions
        self._approvals = approvals or ApprovalService(sessions, clock=clock)
        self._kinds = kinds
        self._settings = settings or get_adoption_settings()
        self._processes = processes

    async def discover(self) -> list[RunningAgent]:
        return await asyncio.to_thread(discover, self._kinds, self._processes)

    async def request_saved(self, *, kind: str, session_id: str, project: Project) -> Approval:
        """Request approval to resume an exact session after it has stopped."""
        cwd = Path(project.repo_path).resolve()
        await asyncio.to_thread(find_saved_session, kind, cwd, session_id)
        async with self._sessions() as db:
            await refuse_second_manager(db, project.name)
        running = await self.discover()
        if any(
            agent.kind == kind
            and (agent.cwd.resolve().is_relative_to(cwd) or session_id in agent.command)
            for agent in running
        ):
            raise AdoptionError(
                f"a {kind} process is still running in {cwd}; use the running-agent flow"
            )
        payload = SavedSessionPayload(
            kind=kind,
            session_id=session_id,
            cwd=str(cwd),
            project=project.name,
            warnings=isolation_warnings(self._settings),
        )
        return await self._approvals.request(ADOPT_SAVED_SESSION, payload.model_dump(mode="json"))

    async def request(
        self,
        pid: int,
        *,
        project: str | None = None,
        requested_by: int | None = None,
        require_tmux: bool = False,
    ) -> AdoptionRequest:
        """Record a pending `adopt_agent` approval for process `pid`."""
        try:
            agent = await asyncio.to_thread(find_running, pid, self._kinds, self._processes)
        except LookupError as error:
            raise AdoptionError(str(error)) from None
        name = project or toplevel(agent.cwd).name
        async with self._sessions() as db:
            await refuse_second_manager(db, name)
            existing = await db.scalar(select(Project).where(Project.name == name))
            if existing is not None and not works_on_project(agent.cwd, Path(existing.repo_path)):
                raise AdoptionError(
                    f"process {pid} runs in {agent.cwd}, outside project {name!r} "
                    f"at {existing.repo_path}"
                )
        pane = await asyncio.to_thread(
            OwnerTmux(self._settings.owner_tmux_socket).pane_of, agent.pid
        )
        if require_tmux and pane is None:
            raise AdoptionError(f"process {pid} is not running in the owner's tmux")
        warnings = isolation_warnings(self._settings)
        payload = AdoptPayload(
            kind=agent.kind,
            pid=agent.pid,
            started_at=agent.started_at,
            cwd=str(agent.cwd),
            project=name,
            pane=pane,
            warnings=warnings,
        )
        approval = await self._approvals.request(
            ADOPT_AGENT, payload.model_dump(mode="json"), agent_id=requested_by
        )
        return AdoptionRequest(approval, agent, warnings)
