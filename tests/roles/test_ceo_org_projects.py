"""The CEO adds server folders as projects, gives each a manager and finds more to take over."""

from pathlib import Path

import pytest

from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Project, Run, RunEvent
from tests.roles.conftest import Org


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty home, so discovery never looks at the developer's own sessions."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return path


async def ceo_actions(org: Org) -> set[tuple[str, str]]:
    events = [e for e in await org.all(RunEvent) if e.kind == "ceo_action"]
    return {(e.payload["tool"], e.payload["actor"]) for e in events}


async def ceo_run(org: Org) -> None:
    async with org.sessions() as db:
        db.add(Run(agent_id=org.ceo, adapter="fake", created_at=org.clock.now()))
        await db.commit()


async def test_the_ceo_adds_a_server_folder_and_it_gets_a_manager_unasked(org: Org) -> None:
    await ceo_run(org)
    folder = org.root / "blog"
    folder.mkdir()

    answer = await org.call("add_project", org.ceo, name="blog", path=str(folder))

    [project] = [p for p in await org.all(Project) if p.name == "blog"]
    assert project.repo_path == str(folder.resolve())
    [manager] = [m for m in await org.all(Agent) if m.project_id == project.id]
    assert (manager.role, manager.reports_to) == ("manager", org.ceo)
    assert (manager.status, manager.adapter) == (AgentStatus.ACTIVE, "fake")
    assert await org.approvals() == []
    assert f"agent {manager.id} manages it" in answer
    actions = await ceo_actions(org)
    assert {("add_project", f"agent:{org.ceo}"), ("assign_manager", f"agent:{org.ceo}")} <= actions


async def test_a_folder_outside_the_allowed_roots_is_not_added(org: Org, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    answer = await org.call("add_project", org.ceo, name="x", path=str(elsewhere))

    assert answer.startswith("Refused:")
    assert "outside the allowed roots" in answer
    assert [p.name for p in await org.all(Project)] == ["site", "shop"]


async def test_a_symlink_out_of_the_roots_cannot_be_added(org: Org, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (org.root / "link").symlink_to(outside)

    answer = await org.call("add_project", org.ceo, name="x", path=str(org.root / "link"))

    assert "outside the allowed roots" in answer


async def test_a_project_without_a_manager_is_reported_to_the_ceo(org: Org) -> None:
    now = org.clock.now()
    async with org.sessions() as db:
        db.add(Project(name="orphan", repo_path="/srv/orphan", created_at=now, updated_at=now))
        await db.commit()

    answer = await org.call("list_projects", org.ceo)

    assert "orphan" in answer
    assert "NO MANAGER" in answer
    assert answer.count("NO MANAGER") == 1


async def test_discovery_lists_git_and_plain_folders_and_hides_the_rest(
    org: Org, tmp_path: Path
) -> None:
    (org.root / "repo" / ".git").mkdir(parents=True)
    (org.root / "repo" / "inside").mkdir()
    (org.root / "plain").mkdir()
    (org.root / ".hidden").mkdir()
    (org.root / "group" / "nested").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (org.root / "escape").symlink_to(outside)
    (org.root / "alias").symlink_to(org.root / "plain")

    answer = await org.call("discover_projects", org.ceo)

    assert f"- {org.root / 'repo'} (git repository)" in answer
    assert f"- {org.root / 'plain'} (folder)" in answer
    assert f"- {org.root / 'group' / 'nested'} (folder)" in answer
    # A git repository is one project: its subfolders are not candidates.
    assert "inside" not in answer
    assert ".hidden" not in answer
    assert "escape" not in answer
    assert "outside" not in answer
    # A link that stays inside the roots lists its target once, not twice.
    assert answer.count(str(org.root / "plain")) == 1


async def test_discovery_marks_folders_that_already_are_projects(org: Org) -> None:
    folder = org.root / "taken"
    folder.mkdir()
    await org.call("add_project", org.ceo, name="taken", path=str(folder))

    answer = await org.call("discover_projects", org.ceo)

    assert f"- {folder} (folder, project taken)" in answer


@pytest.mark.parametrize("root", ["/", ".hidden"])
async def test_discovery_refuses_a_root_it_may_not_look_in(org: Org, root: str) -> None:
    (org.root / ".hidden").mkdir()
    given = str(org.root / root) if root == ".hidden" else root

    answer = await org.call("discover_projects", org.ceo, root=given)

    assert answer.startswith("Refused:")


@pytest.mark.posix_only("saved CLI sessions run through the tmux adapter")
async def test_discovery_lists_running_and_saved_sessions(org: Org, home: Path) -> None:
    project = org.root / "app"
    project.mkdir()
    store = home / ".claude" / "projects" / str(project.resolve()).replace("/", "-")
    store.mkdir(parents=True)
    session_id = "0f4c1a52-3b7e-4c1d-9a55-6a1e9d3c7b10"
    (store / f"{session_id}.jsonl").write_text(
        f'{{"cwd": "{project.resolve()}"}}\n', encoding="utf-8"
    )

    answer = await org.call("discover_projects", org.ceo)

    assert f"- {project}: claude-code {session_id}" in answer


class FakeProcess:
    """What `psutil.process_iter` yields: a pid, a command line and a working directory."""

    def __init__(self, pid: int, command: list[str], cwd: Path) -> None:
        self.pid = pid
        self.info = {"pid": pid, "cmdline": command, "create_time": 1.0}
        self._cwd = cwd

    def cwd(self) -> str:
        return str(self._cwd)


async def test_discovery_lists_running_sessions_inside_the_roots_only(
    org: Org, tmp_path: Path
) -> None:
    mine = org.root / "app"
    mine.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    org.processes += [
        FakeProcess(4101, ["claude"], mine),
        FakeProcess(4102, ["claude"], elsewhere),
    ]

    answer = await org.call("discover_projects", org.ceo)

    assert f"- pid 4101: claude-code in {mine}" in answer
    assert "4102" not in answer
