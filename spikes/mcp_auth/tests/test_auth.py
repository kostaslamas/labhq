import pytest
from starlette.testclient import TestClient

from mcp_auth.app import build_app

TOKEN = "test-token-123"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


INIT = rpc(
    "initialize",
    {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
)


@pytest.fixture(scope="module")
def client():
    with TestClient(build_app(TOKEN), base_url="http://127.0.0.1:8787") as c:
        yield c


def bearer(token: str = TOKEN) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {token}"}


def test_no_token_is_401(client):
    assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401


def test_wrong_token_is_401(client):
    assert client.post("/mcp", json=INIT, headers=bearer("nope")).status_code == 401


def test_wrong_secret_path_is_401(client):
    assert client.post("/mcp/nope", json=INIT, headers=HEADERS).status_code == 401


def test_initialize_returns_json(client):
    r = client.post("/mcp", json=INIT, headers=bearer())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "result" in r.json()


def test_tools_list_has_read_only_tool(client):
    r = client.post("/mcp", json=rpc("tools/list"), headers=bearer())
    assert r.headers["content-type"].startswith("application/json")
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert tools["what_time_is_it"]["annotations"]["readOnlyHint"] is True


def test_tools_call(client):
    r = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "what_time_is_it", "arguments": {}}),
        headers=bearer(),
    )
    assert r.headers["content-type"].startswith("application/json")
    text = r.json()["result"]["content"][0]["text"]
    assert "UTC" in text


def test_secret_path_variant_works(client):
    r = client.post(f"/mcp/{TOKEN}", json=rpc("tools/list"), headers=HEADERS)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["result"]["tools"][0]["name"] == "what_time_is_it"
