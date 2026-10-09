"""Continue a session: adopt a running one, resume a saved one, hand an IDE chat to a CLI.

Running CLI sessions and saved CLI sessions go through the adoption flow (ADR 0005), whose
approvals and moves are reused unchanged. Cursor IDE chats cannot be continued inside labhq:
the hand-off is a task for a CLI agent in the same folder, with the project's latest analysis
as context.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adoption import AdoptionError, Adoptions
from labhq.adoption.record import ensure_project
from labhq.clock import Clock
from labhq.db.models import Approval, Project, Task
from labhq.inventory.model import SessionInfo
from labhq.work import add_task

HANDOFF_TITLE = "Continue the {tool} work in {name}"
HANDOFF_BODY = """The owner worked on this folder in {tool} ({session_id}), which labhq cannot
continue. Pick the work up in {folder} with a CLI agent.
{analysis}
Start by reading git status and git log to see where it stopped."""


@dataclass(frozen=True)
class Continuation:
    """What `continue_session` did: an adoption approval, or a hand-off task."""

    approval: Approval | None = None
    task: Task | None = None


def latest_analysis(data_dir: Path, project: str) -> Path | None:
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in project).strip("-")
    found = sorted((data_dir / "inventory" / "analyses").glob(f"{slug}-*.md"))
    return found[-1] if found else None


async def continue_session(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    adoptions: Adoptions,
    session: SessionInfo,
    *,
    project_name: str,
    data_dir: Path,
) -> Continuation:
    folder = session.folder.resolve()
    if session.pid is not None:
        request = await adoptions.request(session.pid, project=project_name)
        return Continuation(approval=request.approval)
    if session.session_id is None:
        raise AdoptionError("this session has no id to resume")
    async with sessions() as db:
        project = await ensure_project(db, clock, project_name, folder)
        await db.commit()
        if session.resumable:
            return Continuation(approval=await _resume(adoptions, project, session))
        task = await _hand_off(db, clock, session, project_name, folder, data_dir)
        await db.commit()
        return Continuation(task=task)


async def _resume(adoptions: Adoptions, project: Project, session: SessionInfo) -> Approval:
    if session.session_id is None:
        raise AdoptionError("this session has no id to resume")
    return await adoptions.request_saved(
        kind=session.tool, session_id=session.session_id, project=project
    )


async def _hand_off(
    db: AsyncSession,
    clock: Clock,
    session: SessionInfo,
    project_name: str,
    folder: Path,
    data_dir: Path,
) -> Task:
    analysis = latest_analysis(data_dir, project_name)
    context = f"Context: the analysis in {analysis}." if analysis else ""
    return await add_task(
        db,
        clock,
        project=project_name,
        title=HANDOFF_TITLE.format(tool=session.tool, name=project_name),
        description=HANDOFF_BODY.format(
            tool=session.tool,
            session_id=session.session_id,
            folder=folder,
            analysis=context,
        ),
    )
