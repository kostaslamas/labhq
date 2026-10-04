"""Adding projects and agents over HTTP: same services as the CLI, approval before any run."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.adapters.kinds import agent_choices
from labhq.cli.context import Context
from labhq.db.enums import AgentStatus, ApprovalStatus
from labhq.db.models import Agent, Approval, Project
from labhq.worktrees.git import run_git
from tests.auth.conftest import WRITE


def add_project(client: TestClient, repo: Path, name: str = "site", **extra: Any) -> Any:
    return client.post(
        "/api/projects", json={"name": name, "repo_path": str(repo), **extra}, headers=WRITE
    )


def add_agent(client: TestClient, project_id: int, **extra: Any) -> Any:
    body = {"role": "worker", "title": "Coder", "kind": "codex", **extra}
    return client.post(f"/api/projects/{project_id}/agents", json=body, headers=WRITE)


def test_agent_kinds_list_every_registered_kind_with_its_adapter_and_availability(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda binary: "/bin/x" if binary == "codex" else None)
    monkeypatch.setattr("labhq.adapters.kinds._claude_binary", lambda: None)

    response = signed_in.get("/api/agent-kinds")

    assert response.status_code == 200, response.text
    kinds = {kind["name"]: kind for kind in response.json()}
    assert list(kinds) == [choice.name for choice in agent_choices()]
    assert kinds["codex"] == {
        "name": "codex",
        "display_name": "Codex",
        "adapter": "tmux",
        "binary": "codex",
        "available": True,
    }
    assert kinds["claude"]["adapter"] == "claude"
    assert kinds["gemini"]["available"] is False


def test_the_routes_need_a_session(app_client: TestClient, repo: Path) -> None:
    assert app_client.get("/api/agent-kinds").status_code == 401
    assert app_client.get("/api/repository-browser").status_code == 401
    assert add_project(app_client, repo).status_code == 401
    assert add_agent(app_client, 1).status_code == 401


async def test_a_project_is_registered_from_a_repository(
    signed_in: TestClient, repo: Path, context: Context
) -> None:
    response = add_project(signed_in, repo, budget_micros=5_000_000)

    assert response.status_code == 201, response.text
    assert response.json()["repo_path"] == str(repo.resolve())
    async with context.sessions() as db:
        project = await db.scalar(select(Project))
    assert project is not None
    assert (project.name, project.budget_micros) == ("site", 5_000_000)


@pytest.mark.parametrize("make", ["missing", "plain_dir", "no_commit", "relative"])
async def test_a_path_that_is_not_a_repository_with_a_commit_is_refused(
    signed_in: TestClient, tmp_path: Path, context: Context, make: str
) -> None:
    target = tmp_path / make
    if make != "missing":
        target.mkdir()
    if make == "no_commit":
        run_git("init", "--quiet", cwd=target)

    response = signed_in.post(
        "/api/projects",
        json={"name": "x", "repo_path": make if make == "relative" else str(target)},
        headers=WRITE,
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] in {"not_a_repository", "repo_path_not_absolute"}
    if make != "relative":
        assert "is not a git repository with a commit" in error["message"]
    async with context.sessions() as db:
        assert await db.scalar(select(Project.id)) is None


def test_a_project_name_is_unique(signed_in: TestClient, repo: Path) -> None:
    assert add_project(signed_in, repo).status_code == 201

    again = add_project(signed_in, repo)

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "project_exists"


def test_a_negative_budget_is_not_valid(signed_in: TestClient, repo: Path) -> None:
    assert add_project(signed_in, repo, budget_micros=-1).status_code == 422


async def test_a_new_agent_waits_for_an_approval_that_activates_it(
    signed_in: TestClient,
    repo: Path,
    context: Context,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The executor opens its own connection to the configured database.
    monkeypatch.setenv("LABHQ_DATABASE_URL", database_url)
    project_id = add_project(signed_in, repo).json()["id"]

    response = add_agent(signed_in, project_id, budget_micros=1_000_000)

    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["status"], created["adapter"], created["kind"]) == (
        "pending_approval",
        "tmux",
        "codex",
    )
    async with context.sessions() as db:
        agent = await db.get(Agent, created["id"])
        approval = await db.get(Approval, created["approval_id"])
    assert agent is not None and approval is not None
    assert agent.config == {"agent": "codex"}
    assert agent.budget_micros == 1_000_000
    assert approval.payload == {"agent_id": agent.id}

    decision = signed_in.post(
        f"/api/approvals/{approval.id}/decision",
        json={"decision": "approve"},
        headers={**WRITE, "Idempotency-Key": "k1"},
    )

    assert decision.status_code == 200, decision.text
    async with context.sessions() as db:
        agent = await db.get(Agent, created["id"])
        approval = await db.get(Approval, created["approval_id"])
    assert agent is not None and approval is not None
    assert approval.status == ApprovalStatus.EXECUTED
    assert agent.status == AgentStatus.ACTIVE


def test_an_unknown_kind_fails_with_the_valid_ones(signed_in: TestClient, repo: Path) -> None:
    project_id = add_project(signed_in, repo).json()["id"]

    response = add_agent(signed_in, project_id, kind="nope")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_kind"
    assert "valid kinds: claude" in response.json()["error"]["message"]


def test_an_agent_needs_an_existing_project(signed_in: TestClient) -> None:
    response = add_agent(signed_in, 99)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_reporting_lines_follow_the_role_table(signed_in: TestClient, repo: Path) -> None:
    project_id = add_project(signed_in, repo).json()["id"]
    manager = add_agent(signed_in, project_id, role="manager", title="M").json()

    wrong = add_agent(signed_in, project_id, role="worker", reports_to=manager["id"])
    right = add_agent(signed_in, project_id, role="lead", title="L", reports_to=manager["id"])
    unknown = add_agent(signed_in, project_id, role="wizard")
    elsewhere = add_agent(signed_in, project_id, role="lead", reports_to=999)

    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "reporting_line"
    assert right.status_code == 201
    assert right.json()["reports_to"] == manager["id"]
    assert unknown.status_code == 422
    assert elsewhere.status_code == 422
    assert "no agent 999" in elsewhere.json()["error"]["message"]
