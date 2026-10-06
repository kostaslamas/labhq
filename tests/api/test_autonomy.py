from typing import Any

import httpx
import pytest

from labhq.api.app import create_app
from labhq.api.autonomy import router
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from tests.api.conftest import OWNER_HEADER


@pytest.fixture
async def client(context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings) -> Any:
    routers = RouterRegistry()
    routers.register(router)
    app = create_app(context, routers=routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "owner"},
    ) as http:
        yield http


async def test_autonomy_starts_on_and_the_owner_can_pause_and_resume(client: Any) -> None:
    assert (await client.get("/api/autonomy")).json() == {"autonomy": "on"}

    assert (await client.put("/api/autonomy", json={"autonomy": "paused"})).json() == {
        "autonomy": "paused"
    }
    assert (await client.get("/api/autonomy")).json() == {"autonomy": "paused"}

    await client.put("/api/autonomy", json={"autonomy": "on"})
    assert (await client.get("/api/autonomy")).json() == {"autonomy": "on"}


async def test_an_unknown_value_is_refused(client: Any) -> None:
    assert (await client.put("/api/autonomy", json={"autonomy": "maybe"})).status_code == 422


async def test_autonomy_needs_the_owner(client: Any) -> None:
    client.headers.pop(OWNER_HEADER)
    assert (await client.get("/api/autonomy")).status_code == 401
