from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from labhq.api.app import create_app
from labhq.api.deps import ClockDep, OwnerDep, ResolverRegistry, SessionDep
from labhq.api.pagination import Page, PageParamsDep, decode_cursor, encode_cursor, paginate
from labhq.api.routes import RouterRegistry
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from labhq.db.models.work import Project

from .conftest import OWNER_HEADER

SIGNED_IN = {OWNER_HEADER: "kostas"}


class ProjectItem(BaseModel):
    id: int
    name: str


def projects_router() -> APIRouter:
    router = APIRouter(prefix="/projects")

    @router.get("")
    async def projects_list(
        owner: OwnerDep, session: SessionDep, page: PageParamsDep
    ) -> Page[ProjectItem]:
        rows, cursor = await paginate(
            session, select(Project), (Project.created_at, Project.id), page
        )
        return Page(items=[ProjectItem(id=r.id, name=r.name) for r in rows], next_cursor=cursor)

    @router.post("")
    async def projects_create(
        owner: OwnerDep, session: SessionDep, clock: ClockDep, name: str
    ) -> ProjectItem:
        now = clock.now()
        project = Project(name=name, repo_path=f"/repos/{name}", created_at=now, updated_at=now)
        session.add(project)
        await session.commit()
        return ProjectItem(id=project.id, name=project.name)

    return router


@pytest.fixture
async def client(context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings) -> Any:
    routers = RouterRegistry()
    routers.register(projects_router())
    app = create_app(context, routers=routers, resolvers=resolvers, settings=api_settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=SIGNED_IN
    ) as client:
        yield client


async def create(client: httpx.AsyncClient, context: Context, name: str) -> None:
    # A distinct instant per row, so the datetime half of the cursor does real work.
    context.clock.advance(timedelta(seconds=1))  # type: ignore[attr-defined]
    response = await client.post("/api/projects", params={"name": name})
    assert response.status_code == 200


async def test_each_row_appears_exactly_once_when_rows_are_inserted_between_pages(
    client: httpx.AsyncClient, context: Context
) -> None:
    for index in range(5):
        await create(client, context, f"before-{index}")

    seen: list[str] = []
    cursor: str | None = None
    inserted = 0
    while True:
        params = {"limit": "2"} | ({"cursor": cursor} if cursor else {})
        response = await client.get("/api/projects", params=params)
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= 2
        seen.extend(item["name"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
        if inserted < 3:
            await create(client, context, f"during-{inserted}")
            inserted += 1

    expected = [f"before-{i}" for i in range(5)] + [f"during-{i}" for i in range(3)]
    assert sorted(seen) == sorted(expected)
    assert len(seen) == len(set(seen))


async def test_limit_defaults_and_is_capped_by_settings(
    client: httpx.AsyncClient, context: Context
) -> None:
    for index in range(5):
        await create(client, context, f"p{index}")
    default = (await client.get("/api/projects")).json()
    assert len(default["items"]) == 2
    capped = (await client.get("/api/projects", params={"limit": "100"})).json()
    assert len(capped["items"]) == 3


async def test_a_tampered_cursor_is_a_400_envelope(client: httpx.AsyncClient) -> None:
    for cursor in ("not-base64!", encode_cursor([1]), "e30"):
        response = await client.get("/api/projects", params={"cursor": cursor})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_cursor"


def test_cursor_round_trips_utc_datetimes(context: Context) -> None:
    now = context.clock.now()
    assert decode_cursor(encode_cursor([now, 7]), 2) == [now, 7]
