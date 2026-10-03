import logging
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.types import ToolAnnotations
from starlette.testclient import TestClient
from typer.testing import CliRunner

from labhq.cli import app
from labhq.mcp.auth import ensure_token, load_token, token_path
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import ToolRegistry, ToolSpec

TOKEN = "test-token-123"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


INIT = rpc(
    "initialize",
    {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
)


async def echo(text: str) -> str:
    return f"You said {text}."


async def boom() -> str:
    raise RuntimeError("the store is closed")


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec("echo", "Repeat a phrase.", ToolAnnotations(readOnlyHint=True), echo)
    )
    registry.register(ToolSpec("boom", "Always fails.", ToolAnnotations(), boom))
    return registry


@pytest.fixture
def client() -> Iterator[TestClient]:
    # TestClient runs the lifespan the MCP app needs to start its task group.
    with TestClient(build_app(make_registry(), TOKEN), base_url="http://127.0.0.1") as c:
        yield c


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {**HEADERS, "Authorization": f"Bearer {token}"}


def call_tool(client: TestClient, name: str, **arguments: Any) -> httpx.Response:
    payload = rpc("tools/call", {"name": name, "arguments": arguments})
    return client.post("/mcp", json=payload, headers=bearer())


def test_no_token_is_401(client: TestClient) -> None:
    assert (client.post("/mcp", json=INIT, headers=HEADERS)).status_code == 401


def test_wrong_token_is_401(client: TestClient) -> None:
    assert (client.post("/mcp", json=INIT, headers=bearer("nope"))).status_code == 401
    assert (client.post("/mcp/nope", json=INIT, headers=HEADERS)).status_code == 401


def test_header_auth_initialize_list_and_call(client: TestClient) -> None:
    init = client.post("/mcp", json=INIT, headers=bearer())
    assert init.status_code == 200
    assert "result" in init.json()
    listed = client.post("/mcp", json=rpc("tools/list"), headers=bearer())
    assert {t["name"] for t in listed.json()["result"]["tools"]} == {"echo", "boom"}
    called = call_tool(client, "echo", text="hi")
    assert called.json()["result"]["content"][0]["text"] == "You said hi."


def test_secret_path_initialize_list_and_call(client: TestClient) -> None:
    path = f"/mcp/{TOKEN}"
    assert (client.post(path, json=INIT, headers=HEADERS)).status_code == 200
    listed = client.post(path, json=rpc("tools/list"), headers=HEADERS)
    assert listed.status_code == 200
    payload = rpc("tools/call", {"name": "echo", "arguments": {"text": "hi"}})
    called = client.post(path, json=payload, headers=HEADERS)
    assert called.json()["result"]["content"][0]["text"] == "You said hi."


def test_responses_are_json_not_event_stream(client: TestClient) -> None:
    for payload in (INIT, rpc("tools/list")):
        response = client.post("/mcp", json=payload, headers=bearer())
        assert response.headers["content-type"].startswith("application/json")


def test_registered_tool_is_listed_with_annotations(client: TestClient) -> None:
    response = client.post("/mcp", json=rpc("tools/list"), headers=bearer())
    tools = {t["name"]: t for t in response.json()["result"]["tools"]}
    assert tools["echo"]["annotations"]["readOnlyHint"] is True
    assert tools["echo"]["description"] == "Repeat a phrase."
    assert "text" in tools["echo"]["inputSchema"]["properties"]


def test_failing_tool_returns_spoken_sentence_without_traceback(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = call_tool(client, "boom")
    text = response.json()["result"]["content"][0]["text"]
    assert text == "Sorry, that did not work: the store is closed."
    assert "Traceback" not in response.text
    assert "Traceback" in caplog.text


@pytest.mark.posix_only("POSIX file permission bits")
def test_token_file_is_0600_and_stable(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    token = ensure_token(directory)
    assert stat.S_IMODE(token_path(directory).stat().st_mode) == 0o600
    assert ensure_token(directory) == token
    assert load_token(directory) == token


@pytest.mark.posix_only("POSIX file permission bits")
def test_cli_token_shows_rotates_and_logs_nothing(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runner = CliRunner()
    with caplog.at_level(logging.DEBUG):
        first = runner.invoke(app, ["mcp", "token"]).stdout.strip()
        again = runner.invoke(app, ["mcp", "token"]).stdout.strip()
        rotated = runner.invoke(app, ["mcp", "token", "--rotate"]).stdout.strip()
    assert first == again != rotated
    assert load_token(data_dir) == rotated
    assert stat.S_IMODE(token_path(data_dir).stat().st_mode) == 0o600
    assert first not in caplog.text
    assert rotated not in caplog.text


def test_no_log_line_holds_the_token(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        client.post(f"/mcp/{TOKEN}", json=INIT, headers=HEADERS)
        client.post("/mcp", json=rpc("tools/list"), headers=bearer())
    # The httpx logger is the test client's own request line, not the server's.
    server_lines = [r.getMessage() for r in caplog.records if not r.name.startswith("httpx")]
    assert server_lines
    assert not any(TOKEN in line for line in server_lines)
