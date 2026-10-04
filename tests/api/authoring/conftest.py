from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.approvals import router as approvals_router
from labhq.api.authoring import router as authoring_router
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from tests.auth.conftest import LOCAL, auth_env, context, enrolled, settings, signed_in
from tests.worktrees.conftest import isolated_git, remote, repo

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
    routers.register(authoring_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client
