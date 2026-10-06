from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import default_routers
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.cli.context import Context
from tests.auth.conftest import LOCAL, auth_env, context, enrolled, settings, signed_in

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    app = create_app(
        context,
        routers=default_routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client
