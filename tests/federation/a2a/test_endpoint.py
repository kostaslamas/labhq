"""Acceptance 5: every A2A route refuses a bad key, and none reaches an owner or CEO tool."""

import pytest
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from fastapi.routing import APIRoute

from labhq.api.federation.a2a import a2a_router
from labhq.federation.invites import Invites
from labhq.federation.keys import ORDERS
from tests.federation.a2a.conftest import A2aPairing

# Everything the A2A transport exposes, and nothing else.
EXPECTED = {
    ("GET", "/federation/a2a/.well-known/agent-card.json"),
    ("POST", "/federation/a2a"),
}
RPC = "/api/federation/a2a"
# The JSON-RPC methods the SDK dispatches. Each is an A2A operation on tasks, never a tool.
METHODS = sorted(JsonRpcDispatcher.METHOD_TO_MODEL)


def _call(method: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}


def test_the_a2a_router_has_exactly_the_card_and_the_rpc_route() -> None:
    routes = {
        (method, route.path)
        for route in a2a_router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert routes == EXPECTED
    assert all(isinstance(route, APIRoute) for route in a2a_router.routes)


def test_the_rpc_methods_are_the_a2a_task_operations() -> None:
    # A new SDK method must be looked at here before it is reachable through a federation key.
    assert METHODS == [
        "CancelTask",
        "CreateTaskPushNotificationConfig",
        "DeleteTaskPushNotificationConfig",
        "GetExtendedAgentCard",
        "GetTask",
        "GetTaskPushNotificationConfig",
        "ListTaskPushNotificationConfigs",
        "ListTasks",
        "SendMessage",
        "SendStreamingMessage",
        "SubscribeToTask",
    ]


@pytest.mark.parametrize("method", METHODS)
async def test_every_method_refuses_a_missing_wrong_or_malformed_key(
    a2a: A2aPairing, method: str
) -> None:
    for headers in (
        {},
        {"Authorization": "Bearer lhqf_not-a-key-it-was-never-issued-here"},
        {"Authorization": f"Basic {a2a.key}"},
        {"Authorization": a2a.key},
    ):
        async with a2a.http() as client:
            response = await client.post(RPC, json=_call(method), headers=headers)
        assert response.status_code == 401, (method, headers)
        assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("method", METHODS)
async def test_a_revoked_key_is_refused_on_every_method(a2a: A2aPairing, method: str) -> None:
    [invite] = await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).list()
    await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).revoke(invite.id)

    async with a2a.http(a2a.key) as client:
        response = await client.post(RPC, json=_call(method))

    assert response.status_code == 401


async def test_a_key_without_the_scope_cannot_make_the_call(a2a: A2aPairing) -> None:
    reports_only = await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).create(
        scopes=["reports"]
    )
    message = {
        "message": {
            "messageId": "m1",
            "role": "ROLE_USER",
            "parts": [{"text": "do it"}],
            "metadata": {"labhq.orderId": 5},
        }
    }

    async with a2a.http(reports_only.key) as client:
        response = await client.post(
            RPC, json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": message}
        )

    assert response.status_code == 200
    assert "may not make that call" in response.json()["error"]["message"]
    assert ORDERS not in reports_only.invite.scopes


@pytest.mark.parametrize(
    "method", ["SendStreamingMessage", "SubscribeToTask", "GetExtendedAgentCard"]
)
async def test_streaming_and_the_extended_card_are_not_offered(
    a2a: A2aPairing, method: str
) -> None:
    async with a2a.http(a2a.key) as client:
        response = await client.post(RPC, json=_call(method))

    assert "error" in response.json()


async def test_a_key_sees_only_its_own_tasks(a2a: A2aPairing) -> None:
    a = a2a.upstream
    await a.call("delegate_task", a.ceo, project="lab", title="Mine")
    await a.drain()
    other = await Invites(a2a.downstream.sessions, clock=a2a.downstream.clock).create()

    async with a2a.http(other.key) as client:
        got = await client.post(RPC, json={**_call("GetTask"), "params": {"id": "1"}})
        listed = await client.post(RPC, json=_call("ListTasks"))

    assert got.json()["error"]["code"] == -32001  # task not found, not "forbidden"
    assert listed.json()["result"].get("tasks", []) == []
    async with a2a.http(a2a.key) as client:
        mine = await client.post(RPC, json=_call("ListTasks"))
    assert [task["id"] for task in mine.json()["result"]["tasks"]] == ["1"]


async def test_the_federation_key_opens_no_owner_route(a2a: A2aPairing) -> None:
    headers = {"Authorization": f"Bearer {a2a.key}", "Idempotency-Key": "from-a"}
    async with a2a.http() as client:
        for method, path in [
            ("GET", "/api/projects"),
            ("GET", "/api/approvals"),
            ("POST", "/api/approvals/1/decision"),
            ("GET", "/api/org"),
        ]:
            response = await client.request(method, path, headers=headers)
            assert response.status_code in {401, 403, 404, 405, 422}, (path, response.status_code)
            assert response.status_code != 200
