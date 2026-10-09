"""One scan: every tool's sessions, grouped by git root, with no model call and no text."""

import sqlite3
from pathlib import Path

import pytest

from labhq.inventory.model import Action, SessionState
from labhq.inventory.stores import opencode as opencode_module
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import FakeProcess, Scan, make_repo


def test_one_scan_finds_the_sessions_of_every_tool(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    folders = {name: make_repo(tmp_path / "work" / name) for name in ("a", "b", "c", "d", "e", "f")}
    fx.claude(home, folders["a"])
    fx.codex(home, folders["b"])
    fx.gemini(home, folders["c"])
    fx.aider(folders["d"])
    fx.opencode(home, [("ses_1", str(folders["e"]), None, None)])
    fx.cursor_cli(home, "chat-1", {"cwd": str(folders["f"]), "updatedAtMs": fx.EPOCH_MS})
    fx.cursor_ide(home, {"composer-1": (folders["a"], fx.EPOCH_MS)})
    # Aider is found where another tool or a running agent already points.
    running = FakeProcess(7, ["aider"], folders["d"])

    inventory = scanner([running]).scan()

    found = {(s.tool, s.folder) for p in inventory.projects for s in p.sessions}
    assert found == {
        ("claude-code", folders["a"]),
        ("cursor-ide", folders["a"]),
        ("codex", folders["b"]),
        ("gemini", folders["c"]),
        ("aider", folders["d"]),
        ("opencode", folders["e"]),
        ("cursor-agent", folders["f"]),
    }


def test_sessions_group_by_the_git_root_of_their_folder(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "work" / "party")
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    fx.claude(home, nested)
    fx.codex(home, repo)

    (project,) = scanner().scan().projects

    assert project.root == repo.resolve()
    assert project.has_repo
    assert sorted(s.tool for s in project.sessions) == ["claude-code", "codex"]
    assert project.git.branch == "main"
    assert project.git.last_commit_subject == "first commit"


def test_a_folder_without_git_is_a_project_marked_no_repo(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    plain = tmp_path / "scratch"
    plain.mkdir()
    fx.claude(home, plain)

    (project,) = scanner().scan().projects

    assert (project.root, project.has_repo) == (plain.resolve(), False)


def test_a_parent_folder_with_two_projects_gets_a_folder_manager_proposal(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    party = make_repo(tmp_path / "games" / "party")
    chess = make_repo(tmp_path / "games" / "chess")
    lone = make_repo(tmp_path / "other" / "lone")
    for folder in (party, chess, lone):
        fx.claude(home, folder, f"{abs(hash(folder)) % 10**8:08d}-1111-4111-8111-111111111111")

    inventory = scanner().scan()

    assert [(f.folder, f.projects) for f in inventory.folders] == [
        (tmp_path / "games", tuple(sorted((chess.resolve(), party.resolve()))))
    ]


def test_a_running_agent_claims_the_newest_saved_session_of_its_folder(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "party")
    fx.claude(home, repo)
    process = FakeProcess(11, ["claude"], repo)

    (project,) = scanner([process], state=SessionState.WAITING).scan().projects

    (session,) = project.sessions
    assert (session.pid, session.session_id, session.state) == (
        11,
        fx.CLAUDE_ID,
        SessionState.WAITING,
    )
    assert project.proposals[0].action is Action.CONTINUE


def test_idle_time_and_a_proposed_action_follow_the_settings(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "party")
    path = fx.claude(home, repo)
    long_ago = 1_700_000_000
    import os

    os.utime(path, (long_ago, long_ago))

    (project,) = scanner().scan().projects

    assert (
        project.sessions[0].idle_seconds is not None
        and project.sessions[0].idle_seconds > 86_400 * 14
    )
    assert project.proposals[0].action is Action.HISTORY


def test_a_quiet_running_agent_for_a_long_time_is_proposed_for_closing(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "party")
    path = fx.claude(home, repo)
    import os

    old = 1_780_000_000 - 3600 * 20  # twenty hours before the fake clock's 2026-06-01
    os.utime(path, (old, old))
    process = FakeProcess(11, ["claude"], repo)

    (project,) = scanner([process]).scan().projects

    assert project.proposals[0].action is Action.CLOSE


def test_cursor_ide_is_read_only_and_not_resumable(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "party")
    fx.cursor_ide(home, {"c1": (repo, fx.EPOCH_MS)})

    (project,) = scanner().scan().projects

    assert [(s.tool, s.resumable) for s in project.sessions] == [("cursor-ide", False)]


def test_the_scan_calls_no_model_and_reads_no_conversation_text(
    home: Path, tmp_path: Path, scanner: Scan, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path / "party")
    fx.claude(home, repo)
    fx.codex(home, repo)
    fx.gemini(home, repo)
    fx.aider(repo)
    fx.opencode(home, [("ses_1", str(repo), None, None)])
    fx.cursor_cli(home, "chat-1", {"cwd": str(repo), "updatedAtMs": fx.EPOCH_MS})
    fx.cursor_ide(home, {"composer-1": (repo, fx.EPOCH_MS)})

    # No adapter may be built: a scan that reached a model would have to create one.
    from labhq.adapters import AdapterRegistry, RunRequest

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the scan used an adapter")

    monkeypatch.setattr(AdapterRegistry, "create", forbidden)
    monkeypatch.setattr("labhq.adapters.fake.FakeAdapter.start", forbidden)
    assert RunRequest  # imported to prove the module loads without side effects

    statements: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)  # type: ignore[call-overload]
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(opencode_module.sqlite3, "connect", spying_connect)

    inventory = scanner().scan()

    assert len(inventory.projects[0].sessions) == 7
    assert fx.SECRET_TEXT not in repr(inventory)
    assert fx.SECRET_TOKEN not in repr(inventory)
    sql = " ".join(statements).lower()
    for private in ("message", "bubbleid", "blobs", "accesstoken", "cursorauth"):
        assert private not in sql
    assert statements, "the SQLite stores were not queried at all"
