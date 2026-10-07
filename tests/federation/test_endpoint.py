"""Acceptance 4 and 6: the endpoint rejects every call without a valid key and offers no tool."""

from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute

from labhq.api.app import API_PREFIX, create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.federation import router
from labhq.api.routes import default_routers
from labhq.api.settings import ApiSettings
from labhq.federation.keys import ORDERS, REPORTS
from labhq.federation.nodes import Nodes
from tests.federation.conftest import NODE_NAME, Pairing

# Everything a downstream instance may do, and nothing else.
EXPECTED = {
    ("GET", "/api/federation/orders"),
    ("POST", "/api/federation/orders/{order_id}/ack"),
    ("POST", "/api/federation/reports"),
}
CONCRETE = [
    ("GET", "/api/federation/orders", None),
    ("POST", "/api/federation/orders/1/ack", None),
    (
        "POST",
        "/api/federation/reports",
        {"order_id": 1, "seq": 1, "status": "ready", "summary": "done"},
    ),
]


def _app(pairing: Pairing):
    return create_app(
        pairing.upstream.context,
        resolvers=ResolverRegistry(),
        settings=ApiSettings(ui_dir=Path("/nonexistent")),
    )


def _client(pairing: Pairing) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(pairing)), base_url="http://upstream.test"
    )


def test_the_endpoint_has_exactly_three_routes_and_none_for_tools() -> None:
    # The router's own routes: FastAPI wraps an included router, so the app does not list them.
    assert all(isinstance(route, APIRoute) for route in router.routes)
    federation = {
        (method, f"{API_PREFIX}{route.path}")
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    mounted = [spec for spec in default_routers if spec.router is router]

    assert federation == EXPECTED
    assert len(mounted) == 1
    # Public means "no owner session"; each route authenticates a federation key itself.
    assert mounted[0].public
    # No federation route reaches the owner's or the CEO's tools, approvals or the MCP server.
    for _, path in federation:
        for forbidden in ("mcp", "approval", "ceo", "passkey", "tool"):
            assert forbidden not in path


@pytest.mark.parametrize(("method", "path", "body"), CONCRETE)
async def test_every_route_refuses_a_call_without_a_valid_key(
    pairing: Pairing, method: str, path: str, body: dict[str, object] | None
) -> None:
    async with _client(pairing) as client:
        for headers in (
            {},
            {"Authorization": "Bearer lhqf_not-the-key-at-all-0000000000"},
            {"Authorization": "Basic abc"},
            {"X-Test-Owner": "owner"},
        ):
            response = await client.request(method, path, json=body, headers=headers)

            assert response.status_code == 401, headers
            assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path", "body"), CONCRETE)
async def test_a_revoked_key_gets_the_answer_an_unknown_key_gets(
    pairing: Pairing, method: str, path: str, body: dict[str, object] | None
) -> None:
    headers = {"Authorization": f"Bearer {pairing.key}"}
    async with _client(pairing) as client:
        unknown = await client.request(
            method, path, json=body, headers={"Authorization": "Bearer lhqf_" + "z" * 40}
        )
        await Nodes(pairing.upstream.sessions, clock=pairing.upstream.clock).revoke(NODE_NAME)
        revoked = await client.request(method, path, json=body, headers=headers)

    assert revoked.status_code == unknown.status_code == 401
    assert revoked.json() == unknown.json()


@pytest.mark.parametrize(
    ("scopes", "path", "method", "body"),
    [
        ([REPORTS], "/api/federation/orders", "GET", None),
        ([ORDERS], "/api/federation/reports", "POST", CONCRETE[2][2]),
    ],
)
async def test_a_key_holds_only_the_scopes_it_was_added_with(
    upstream,
    downstream,
    scopes,
    path,
    method,
    body,
) -> None:
    from labhq.federation.invites import Invites

    invitation = await Invites(downstream.sessions, clock=downstream.clock).create()
    await Nodes(upstream.sessions, clock=upstream.clock).add(
        "https://b.example", invitation.key, project="lab", scopes=scopes
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(
                upstream.context,
                resolvers=ResolverRegistry(),
                settings=ApiSettings(ui_dir=Path("/nonexistent")),
            )
        ),
        base_url="http://upstream.test",
    )
    async with client:
        response = await client.request(
            method, path, json=body, headers={"Authorization": f"Bearer {invitation.key}"}
        )

    assert response.status_code == 401


async def test_an_unlisted_federation_path_is_not_found_even_with_a_valid_key(
    pairing: Pairing,
) -> None:
    async with _client(pairing) as client:
        response = await client.get(
            "/api/federation/tasks", headers={"Authorization": f"Bearer {pairing.key}"}
        )

    assert response.status_code == 404


async def test_a_federation_key_opens_nothing_outside_the_federation_routes(
    pairing: Pairing,
) -> None:
    headers = {"Authorization": f"Bearer {pairing.key}"}
    async with _client(pairing) as client:
        for path in (
            "/api/approvals",
            "/api/org/ceo",
            "/api/projects",
            "/api/today",
            "/mcp",
        ):
            response = await client.get(path, headers=headers)

            assert response.status_code in {401, 404}, path


async def test_one_node_cannot_acknowledge_or_report_on_another_nodes_order(
    pairing: Pairing,
) -> None:
    from labhq.federation.invites import Invites

    a = pairing.upstream
    other = await Invites(pairing.downstream.sessions, clock=pairing.downstream.clock).create()
    async with a.sessions() as db:
        from labhq.db.models import Project

        project = Project(
            name="second", repo_path="/srv/b", created_at=a.clock.now(), updated_at=a.clock.now()
        )
        db.add(project)
        await db.commit()
    await Nodes(a.sessions, clock=a.clock).add(
        "https://c.example", other.key, project="second", name="lab-c"
    )
    await a.call("delegate_task", a.ceo, project="lab", title="For B")
    await a.drain()

    async with _client(pairing) as client:
        theirs = {"Authorization": f"Bearer {other.key}"}
        ack = await client.post("/api/federation/orders/1/ack", headers=theirs)
        report = await client.post(
            "/api/federation/reports",
            headers=theirs,
            json={"order_id": 1, "seq": 1, "status": "ready", "summary": "mine now"},
        )
        orders = await client.get("/api/federation/orders", headers=theirs)

    assert ack.status_code == 404
    assert report.status_code == 404
    assert orders.json() == {"orders": []}
