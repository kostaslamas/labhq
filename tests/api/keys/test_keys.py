"""The owner sends control keys to a tmux agent over the API; nobody else can."""

import pytest
from fastapi.testclient import TestClient

from labhq.api.keys.routes import get_key_service
from tests.api.org.conftest import app_client, auth_env, context, enrolled, settings, signed_in
from tests.auth.conftest import WRITE
from tests.controlkeys.conftest import FakePanes, World, sessions, world

__all__ = [
    "FakePanes",
    "app_client",
    "auth_env",
    "context",
    "enrolled",
    "sessions",
    "settings",
    "signed_in",
    "world",
]


@pytest.fixture
def client(signed_in: TestClient, world: World) -> TestClient:
    signed_in.app.dependency_overrides[get_key_service] = lambda: world.service  # type: ignore[attr-defined]
    return signed_in


def test_the_owner_sends_escape_then_shift_tab(client: TestClient, world: World) -> None:
    agent = world.ids["worker_a"]

    first = client.post(f"/api/agents/{agent}/keys", json={"key": "escape"}, headers=WRITE)
    second = client.post(f"/api/agents/{agent}/keys", json={"key": "shift_tab"}, headers=WRITE)

    assert first.status_code == second.status_code == 200
    assert second.json() == {"key": "shift_tab", "screen": "mode: auto-accept"}
    assert [keys for _, keys, _ in world.panes.sent] == [("Escape",), ("BTab",)]


def test_the_keys_of_a_tmux_agent_are_listed_and_an_sdk_agent_has_none(
    client: TestClient, world: World
) -> None:
    tmux = client.get(f"/api/agents/{world.ids['worker_a']}/keys")
    sdk = client.get(f"/api/agents/{world.ids['sdk']}/keys")

    assert tmux.json() == {"keys": ["escape", "shift_tab", "ctrl_c"], "live": True}
    assert sdk.json() == {"keys": [], "live": False}


@pytest.mark.parametrize(
    ("key", "agent", "status", "code"),
    [
        ("hello", "worker_a", 422, "key_refused"),
        ("Escape", "worker_a", 422, "key_refused"),
        ("escape", "sdk", 409, "headless"),
    ],
)
def test_refusals_carry_a_status_and_a_code(
    client: TestClient, world: World, key: str, agent: str, status: int, code: str
) -> None:
    response = client.post(f"/api/agents/{world.ids[agent]}/keys", json={"key": key}, headers=WRITE)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert world.panes.sent == []


def test_an_unknown_agent_is_not_found(client: TestClient) -> None:
    response = client.post("/api/agents/9999/keys", json={"key": "escape"}, headers=WRITE)

    assert response.status_code == 404


def test_the_screen_is_read_without_sending_a_key(client: TestClient, world: World) -> None:
    response = client.get(f"/api/agents/{world.ids['worker_a']}/screen")

    assert response.json() == {"screen": "mode: auto-accept"}
    assert world.panes.sent == []


def test_every_route_refuses_a_request_without_an_owner_session(
    app_client: TestClient, world: World
) -> None:
    app_client.app.dependency_overrides[get_key_service] = lambda: world.service  # type: ignore[attr-defined]
    agent = world.ids["worker_a"]

    responses = [
        app_client.post(f"/api/agents/{agent}/keys", json={"key": "escape"}, headers=WRITE),
        app_client.get(f"/api/agents/{agent}/keys"),
        app_client.get(f"/api/agents/{agent}/screen"),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert world.panes.sent == []
