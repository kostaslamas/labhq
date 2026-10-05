"""Saved session choices are bound to one CLI and one exact working directory."""

import json
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from labhq.adapters.tmux.agents import default_kinds
from labhq.adoption.move import AdoptionEngine
from labhq.adoption.request import SavedSessionPayload
from labhq.adoption.saved import find_saved_session, list_saved_sessions
from labhq.adoption.session import AdoptedSession, continue_argv
from labhq.adoption.state import state_of
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent, Project


def test_discovery_lists_only_sessions_in_the_chosen_directory(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    home = tmp_path / "home"
    codex = home / ".codex" / "sessions" / "2026" / "10" / "05"
    codex.mkdir(parents=True)
    codex_id, other_id = str(uuid4()), str(uuid4())
    for session_id, cwd in ((codex_id, project), (other_id, other)):
        (codex / f"rollout-{session_id}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": session_id, "cwd": str(cwd)}})
            + "\n"
            + json.dumps({"type": "user", "payload": {"secret": "never show"}}),
            encoding="utf-8",
        )
    claude = home / ".claude" / "projects" / str(project).replace("/", "-")
    claude.mkdir(parents=True)
    claude_id = str(uuid4())
    (claude / f"{claude_id}.jsonl").write_text(
        json.dumps({"type": "mode"}) + "\n" + json.dumps({"type": "user", "cwd": str(project)}),
        encoding="utf-8",
    )
    gemini = home / ".gemini" / "tmp" / "hash"
    (gemini / "chats").mkdir(parents=True)
    (gemini / ".project_root").write_text(str(project), encoding="utf-8")
    gemini_id = str(uuid4())
    (gemini / "chats" / "session-any.json").write_text(
        json.dumps({"sessionId": gemini_id, "messages": [{"secret": "never show"}]}),
        encoding="utf-8",
    )
    (project / ".aider.chat.history.md").write_text("history", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(home / ".gemini"))

    assert [row.session_id for row in list_saved_sessions("codex", project)] == [codex_id]
    assert [row.session_id for row in list_saved_sessions("claude-code", project)] == [claude_id]
    assert [row.session_id for row in list_saved_sessions("gemini", project)] == [gemini_id]
    assert [row.session_id for row in list_saved_sessions("aider", project)] == [
        ".aider.chat.history.md"
    ]
    assert list_saved_sessions("claude-code", other) == []
    try:
        find_saved_session("codex", project, other_id)
    except LookupError:
        pass
    else:
        raise AssertionError("a session from another directory was accepted")


def test_selected_resume_uses_the_exact_id_and_keeps_agent_flags(tmp_path: Path) -> None:
    session = AdoptedSession("saved", tmp_path, tmp_path / "state")
    selected = str(uuid4())
    for kind_name in ("claude-code", "codex", "gemini", "aider"):
        kind = default_kinds.get(kind_name)
        argv = continue_argv(
            kind, session, python=sys.executable, sandbox=(), selected_session_id=selected
        )
        if kind_name != "aider":
            assert selected in argv
            assert "--last" not in argv and "--continue" not in argv
        if kind_name == "codex":
            assert "--yolo" in argv


async def test_approved_saved_session_starts_as_manager_with_selected_id(
    tmp_path: Path, database_url: str, monkeypatch
) -> None:
    project_dir = tmp_path / "plain"
    project_dir.mkdir()
    store = tmp_path / "claude"
    directory = store / "projects" / str(project_dir).replace("/", "-")
    directory.mkdir(parents=True)
    selected = str(uuid4())
    (directory / f"{selected}.jsonl").write_text(
        json.dumps({"type": "user", "cwd": str(project_dir)}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(store))
    now = SystemClock().now()
    db_engine = create_engine(database_url)
    sessions = session_factory(db_engine)
    async with sessions() as db:
        db.add(Project(name="plain", repo_path=str(project_dir), created_at=now, updated_at=now))
        await db.commit()

    class FakeServer:
        def __init__(self) -> None:
            self.state_dir = tmp_path / "tmux"
            self.launched: list[str] = []

        def new_session(self, name: str, *, cwd: Path, argv: list[str], variables: dict) -> None:
            assert cwd == project_dir
            self.launched = argv

    server = FakeServer()
    engine = AdoptionEngine(server=lambda: server, database_url=lambda: database_url)
    result = await engine.adopt_saved(
        SavedSessionPayload(
            kind="claude-code", session_id=selected, cwd=str(project_dir), project="plain"
        )
    )
    assert selected in server.launched
    assert "--continue" not in server.launched
    async with sessions() as db:
        manager = await db.scalar(select(Agent).where(Agent.id == result["agent_id"]))
        assert manager is not None and manager.role == "manager"
        state = state_of(manager)
        assert state is not None and state.session_id == selected
        assert state.original_pid is None
    await db_engine.dispose()
