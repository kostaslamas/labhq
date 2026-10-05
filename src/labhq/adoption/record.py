"""Record an adoption: the project if missing, the manager under the CEO, the first status.

The status lists the changes left uncommitted at the move, so the owner can decide whether
they become the first task. `.labhq/status.md` is written only when the agent has none.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import AgentKind
from labhq.adoption.checkout import is_git_repository
from labhq.adoption.request import AdoptPayload, SavedSessionPayload, refuse_second_manager
from labhq.adoption.session import AdoptedSession, file_digest
from labhq.adoption.state import AdoptionState, store_state
from labhq.callcenter.status.format import StatusFields, render_status
from labhq.callcenter.status.ingest import STATUS_RELATIVE_PATH, status_fingerprint
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Project, StatusUpdate
from labhq.hierarchy import CEO, MANAGER, check_reports_to
from labhq.hierarchy.service import CEO_TITLE
from labhq.usage.plan import agent_kind

TMUX_ADAPTER = "tmux"
DECIDE_UNCOMMITTED = "Decide whether the uncommitted changes become the first task"


@dataclass(frozen=True)
class Adopted:
    """What the move left behind, for the record."""

    kind: AgentKind
    session: AdoptedSession
    repo: Path
    session_id: str | None
    uncommitted: list[str]
    baseline: str
    last_screen: str | None


def adoption_status(uncommitted: list[str], *, git: bool = True) -> StatusFields:
    if not git:
        return StatusFields(
            summary="Adopted by labhq as this project's manager. "
            "Existing folder files were left in place."
        )
    left = (
        "Uncommitted changes at the move were left in place: " + ", ".join(uncommitted) + "."
        if uncommitted
        else "There were no uncommitted changes at the move."
    )
    decide = (DECIDE_UNCOMMITTED,) if uncommitted else ()
    return StatusFields(
        summary=f"Adopted by labhq as this project's manager. {left}",
        next=decide,
        refs=tuple(uncommitted),
    )


async def ensure_project(db: AsyncSession, clock: Clock, name: str, repo: Path) -> Project:
    project = await db.scalar(select(Project).where(Project.name == name))
    if project is not None:
        return project
    now = clock.now()
    project = Project(name=name, repo_path=str(repo), created_at=now, updated_at=now)
    db.add(project)
    await db.flush()
    return project


async def ensure_ceo(db: AsyncSession, clock: Clock, adapter: str) -> Agent:
    query = select(Agent).where(Agent.role == CEO, Agent.status != AgentStatus.RETIRED)
    ceo = await db.scalar(query.order_by(Agent.id).limit(1))
    if ceo is not None:
        return ceo
    now = clock.now()
    ceo = Agent(
        project_id=None,
        role=CEO,
        title=CEO_TITLE,
        reports_to=None,
        adapter=adapter,
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(ceo)
    await db.flush()
    return ceo


async def record_adoption(
    db: AsyncSession,
    clock: Clock,
    *,
    request: AdoptPayload | SavedSessionPayload,
    adopted: Adopted,
    ceo_adapter: str,
) -> dict[str, Any]:
    await refuse_second_manager(db, request.project)
    project = await ensure_project(db, clock, request.project, adopted.repo)
    ceo = await ensure_ceo(db, clock, ceo_adapter)
    check_reports_to(MANAGER, ceo.role)
    now = clock.now()
    # The owner approved this agent by approving its adoption; it starts active.
    manager = Agent(
        project_id=project.id,
        role=MANAGER,
        title=f"{project.name} manager",
        reports_to=ceo.id,
        adapter=TMUX_ADAPTER,
        config={"agent": adopted.kind.name},
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session = adopted.session
    store_state(
        manager,
        AdoptionState(
            kind=adopted.kind.name,
            cwd=str(session.cwd),
            repo=str(adopted.repo),
            tmux_session=session.name,
            state_dir=str(session.state_dir),
            original_pid=request.pid if isinstance(request, AdoptPayload) else None,
            session_id=adopted.session_id,
            uncommitted=adopted.uncommitted,
            baseline=adopted.baseline,
            signal=file_digest(session.signal_path),
            statusline=file_digest(session.statusline_path),
        ),
    )
    db.add(manager)
    await db.flush()
    fields = adoption_status(adopted.uncommitted, git=is_git_repository(adopted.repo))
    status_file = session.cwd / STATUS_RELATIVE_PATH
    if not status_file.exists():
        status_file.write_text(render_status(fields), encoding="utf-8")
    db.add(
        StatusUpdate(
            agent_id=manager.id,
            task_id=None,
            fields=fields.model_dump(mode="json"),
            fingerprint=status_fingerprint(fields),
            observed_at=now,
        )
    )
    await db.flush()
    return {
        "agent_id": manager.id,
        "project_id": project.id,
        "reports_to": ceo.id,
        "agent_kind": agent_kind(TMUX_ADAPTER, manager.config),
        "tmux_session": session.name,
        "session_id": adopted.session_id,
        "uncommitted": adopted.uncommitted,
    }
