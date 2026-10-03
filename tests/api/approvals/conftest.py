from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.approvals import router as approvals_router
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.approvals import PUSH_ACTION, ApprovalService, push_payload
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from labhq.db.models import Approval
from labhq.worktrees import Worktree, Worktrees
from tests.auth.conftest import LOCAL, auth_env, context, enrolled, settings, signed_in
from tests.db.factories import project_agent_task
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file

__all__ = [
    "auth_env",
    "context",
    "enrolled",
    "isolated_git",
    "remote",
    "repo",
    "settings",
    "signed_in",
]


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(approvals_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui", default_page_size=2, max_page_size=3),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


@pytest.fixture
def service(context: Context) -> ApprovalService:
    return ApprovalService(context.sessions, clock=context.clock)


@pytest.fixture
async def ids(context: Context) -> dict[str, int]:
    async with context.sessions() as db:
        project, agent, task = await project_agent_task(db, context.clock)
        await db.commit()
    return {"project": project.id, "agent": agent.id, "task": task.id}


@pytest.fixture
async def light(service: ApprovalService, ids: dict[str, int]) -> Approval:
    return await service.request(
        "assign_task", {"note": "x"}, task_id=ids["task"], agent_id=ids["agent"]
    )


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "publish me")
    commit_file(worktree.path, "work.txt")
    return worktree


@pytest.fixture
async def heavy(
    service: ApprovalService, ids: dict[str, int], repo: Path, worktree: Worktree
) -> Approval:
    return await service.request(
        PUSH_ACTION,
        push_payload(repo, worktree.branch),
        task_id=ids["task"],
        agent_id=ids["agent"],
    )
