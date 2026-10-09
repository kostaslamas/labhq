"""Close never interrupts a turn; continue adopts, resumes or hands off; folders on acceptance."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.adoption import ADOPT_AGENT, ADOPT_SAVED_SESSION, AdoptionError, Adoptions
from labhq.adoption.discovery import all_processes
from labhq.approvals import ApprovalService
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, ApprovalStatus
from labhq.db.models import Agent, Project, Task
from labhq.hierarchy import MANAGER
from labhq.inventory import register  # noqa: F401
from labhq.inventory.close import CLOSE_SESSION, SessionCloser
from labhq.inventory.continuing import continue_session
from labhq.inventory.folders import (
    CREATE_FOLDER_MANAGER,
    FolderManagerEngine,
    FolderManagerPayload,
    propose,
)
from labhq.inventory.model import FolderProposal, SessionInfo, SessionState
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import FixedProbe, Scan, make_repo

PROGRAM = "inventory_fake_agent.py"


@pytest.fixture
def agent_process(tmp_path: Path):
    """A real process the process table sees as a CLI named like the fake kind."""
    script = tmp_path / PROGRAM
    script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path)
    time.sleep(0.3)
    yield process
    process.kill()
    process.wait()


def fake_kinds() -> AgentKinds:
    kinds = default_kinds.copy()
    from dataclasses import replace

    kinds.register(
        replace(default_kinds.get("claude-code"), name="fake-cli", processes=(PROGRAM,)),
    )
    return kinds


def running_session(pid: int, folder: Path) -> SessionInfo:
    import psutil

    return SessionInfo(
        tool="fake-cli",
        session_id="s1",
        folder=folder,
        state=SessionState.IDLE,
        last_activity=None,
        idle_seconds=3600.0,
        pid=pid,
        started_at=psutil.Process(pid).create_time(),
    )


@pytest.fixture
def approvals(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> ApprovalService:
    return ApprovalService(sessions, clock=clock)


async def test_an_idle_session_is_closed_after_approval_and_its_process_ends(
    agent_process: subprocess.Popen[bytes], tmp_path: Path, approvals: ApprovalService
) -> None:
    closer = SessionCloser(kinds=fake_kinds(), probe=FixedProbe(SessionState.IDLE))
    approval = await closer.request(approvals, running_session(agent_process.pid, tmp_path))
    assert (approval.type, approval.status) == (CLOSE_SESSION, ApprovalStatus.PENDING)
    assert agent_process.poll() is None  # nothing ends before the owner approves

    result = closer.run(approval.payload)

    agent_process.wait(timeout=10)
    assert result["closed"] == agent_process.pid and result["alive"] is False


async def test_a_session_in_the_middle_of_a_turn_is_never_closed(
    agent_process: subprocess.Popen[bytes], tmp_path: Path, approvals: ApprovalService
) -> None:
    session = running_session(agent_process.pid, tmp_path)
    idle = SessionCloser(kinds=fake_kinds(), probe=FixedProbe(SessionState.IDLE))
    approval = await idle.request(approvals, session)
    working = SessionCloser(kinds=fake_kinds(), probe=FixedProbe(SessionState.RUNNING))

    with pytest.raises(AdoptionError, match="middle of a turn"):
        await working.request(approvals, session)
    # The agent started a turn after the request: the executor looks again.
    with pytest.raises(AdoptionError, match="middle of a turn"):
        working.run(approval.payload)

    assert agent_process.poll() is None


async def test_a_saved_session_has_no_process_to_close(
    approvals: ApprovalService, tmp_path: Path
) -> None:
    saved = SessionInfo("claude-code", "x", tmp_path, SessionState.IDLE, None, 1.0)

    with pytest.raises(AdoptionError, match="saved one has no process"):
        await SessionCloser().request(approvals, saved)


async def test_the_pid_of_another_process_is_refused(
    agent_process: subprocess.Popen[bytes], tmp_path: Path, approvals: ApprovalService
) -> None:
    session = running_session(agent_process.pid, tmp_path)
    closer = SessionCloser(kinds=fake_kinds(), probe=FixedProbe())
    approval = await closer.request(approvals, session)
    payload = {
        **approval.payload,
        "started_at": session.started_at + 5 if session.started_at else 1,
    }

    with pytest.raises(AdoptionError, match="no longer the agent"):
        closer.run(payload)
    assert agent_process.poll() is None
    assert all_processes  # discovery is the process table's, as for adoption


async def test_continuing_a_running_session_asks_to_adopt_it(
    agent_process: subprocess.Popen[bytes],
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    repo = make_repo(tmp_path / "party")
    adoptions = Adoptions(sessions, clock=clock, kinds=fake_kinds())
    import psutil

    session = SessionInfo(
        "fake-cli",
        None,
        repo,
        SessionState.IDLE,
        None,
        5.0,
        pid=agent_process.pid,
        started_at=psutil.Process(agent_process.pid).create_time(),
    )
    # The process runs in tmp_path, not the repo; adoption reads its real working directory.
    result = await continue_session(
        sessions, clock, adoptions, session, project_name="party", data_dir=tmp_path
    )

    assert result.approval is not None and result.approval.type == ADOPT_AGENT


async def test_continuing_a_saved_cli_session_asks_to_resume_it(
    home: Path, tmp_path: Path, sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    repo = make_repo(tmp_path / "party")
    fx.opencode(home, [("ses_1", str(repo), None, None)])
    scanned = SessionScanner(
        settings=InventorySettings(use_gh=False),
        clock=clock,
        processes=lambda: [],
        probe=FixedProbe(),
        home=home,
        environ={},
    ).scan()
    (session,) = scanned.projects[0].sessions

    result = await continue_session(
        sessions,
        clock,
        Adoptions(sessions, clock=clock),
        session,
        project_name="party",
        data_dir=tmp_path,
    )

    assert result.approval is not None and result.approval.type == ADOPT_SAVED_SESSION
    assert result.approval.payload["session_id"] == "ses_1"
    assert result.approval.payload["kind"] == "opencode"


async def test_a_cursor_ide_chat_is_handed_off_to_a_cli_agent_with_the_analysis(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    repo = make_repo(tmp_path / "party")
    fx.cursor_ide(home, {"c1": (repo, fx.EPOCH_MS)})
    analyses = tmp_path / "data" / "inventory" / "analyses"
    analyses.mkdir(parents=True)
    (analyses / "party-20260601-000000.md").write_text("# analysis\n", encoding="utf-8")
    (session,) = scanner().scan().projects[0].sessions

    result = await continue_session(
        sessions,
        clock,
        Adoptions(sessions, clock=clock),
        session,
        project_name="party",
        data_dir=tmp_path / "data",
    )

    assert result.approval is None and result.task is not None
    async with sessions() as db:
        task = await db.get_one(Task, result.task.id)
        project = await db.get_one(Project, task.project_id)
    assert project.repo_path == str(repo.resolve())
    assert "party-20260601-000000.md" in task.description
    assert str(repo.resolve()) in task.description and "CLI agent" in task.description


async def test_a_folder_manager_exists_only_after_the_owner_approves(
    tmp_path: Path,
    approvals: ApprovalService,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    database_url: str,
) -> None:
    folder = tmp_path / "games"
    proposal = FolderProposal(folder, (folder / "party", folder / "chess"))

    approval = await propose(approvals, proposal)
    async with sessions() as db:
        assert list(await db.scalars(select(Agent).where(Agent.role == MANAGER))) == []

    created = await FolderManagerEngine(clock=clock, database_url=lambda: database_url).create(
        FolderManagerPayload.model_validate(approval.payload)
    )

    assert approval.type == CREATE_FOLDER_MANAGER
    async with sessions() as db:
        manager = await db.get_one(Agent, created["agent_id"])
        ceo = await db.get_one(Agent, manager.reports_to)
    assert (manager.role, manager.status, ceo.role) == (MANAGER, AgentStatus.ACTIVE, "ceo")
    assert manager.config["folder_manager"]["projects"] == [str(p) for p in proposal.projects]
