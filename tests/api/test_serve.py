import os
import signal
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.types import ToolAnnotations
from starlette.testclient import TestClient

import labhq
from labhq.api.app import LifespanError, asgi_lifespan, create_server_app
from labhq.api.deps import ResolverRegistry
from labhq.api.settings import ApiSettings
from labhq.mcp.auth import load_token
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import ToolRegistry, ToolSpec

TOKEN = "test-token-123"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
READY_LINE = "Application startup complete"
DEADLINE_SECONDS = 60


async def echo(text: str) -> str:
    return text


def mcp_app() -> Any:
    registry = ToolRegistry()
    registry.register(ToolSpec("echo", "Repeat.", ToolAnnotations(readOnlyHint=True), echo))
    return build_app(registry, TOKEN)


def server_client(settings: ApiSettings) -> TestClient:
    app = create_server_app(None, mcp_app(), settings=settings, resolvers=ResolverRegistry())
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    path = tmp_path / "dist"
    (path / "assets").mkdir(parents=True)
    (path / "index.html").write_text("<!doctype html><title>labhq</title>")
    (path / "assets" / "app.js").write_text("console.log('labhq')")
    return path


@pytest.fixture
def client(api_settings: ApiSettings) -> Iterator[TestClient]:
    with server_client(api_settings) as c:
        yield c


def test_one_app_answers_the_api_and_mcp(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"version": labhq.__version__}
    auth = {**MCP_HEADERS, "Authorization": f"Bearer {TOKEN}"}
    for path, headers in (("/mcp", auth), (f"/mcp/{TOKEN}", MCP_HEADERS)):
        response = client.post(path, json=INIT, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert "result" in response.json()


def test_mcp_auth_is_unchanged_behind_the_api(client: TestClient) -> None:
    # The MCP guard's own body, not the API envelope: MCP clients see what they saw before.
    for path, headers in (
        ("/mcp", MCP_HEADERS),
        ("/mcp", {**MCP_HEADERS, "Authorization": "Bearer nope"}),
        ("/mcp/nope", MCP_HEADERS),
    ):
        response = client.post(path, json=INIT, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"error": "unauthorized"}


def test_without_a_built_ui_the_root_is_a_404_envelope(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_built_ui_is_served_with_a_single_page_fallback(ui_dir: Path) -> None:
    settings = ApiSettings(ui_dir=ui_dir)
    with server_client(settings) as client:
        assert "<title>labhq</title>" in client.get("/").text
        assert "<title>labhq</title>" in client.get("/approvals/42").text
        assert client.get("/assets/app.js").text == "console.log('labhq')"
        assert client.get("/assets/missing.js").status_code == 404
        unknown = client.get("/api/nowhere")
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "not_found"
        assert client.get("/api/health").json() == {"version": labhq.__version__}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def labhq_process(*args: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "labhq", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_labhq_serve_answers_health_and_mcp_on_one_port(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    env = {**os.environ, "LABHQ_DATA_DIR": str(data_dir), "PYTHONUNBUFFERED": "1"}
    env.pop("LABHQ_DATABASE_URL", None)
    env["LABHQ_API_UI_DIR"] = str(tmp_path / "no-ui")
    init = labhq_process("init", env=env)
    init.communicate(timeout=DEADLINE_SECONDS)
    assert init.returncode == 0

    port = free_port()
    server = labhq_process("serve", "--port", str(port), env=env)
    try:
        assert server.stderr is not None
        for line in server.stderr:
            if READY_LINE in line:
                break
        else:
            pytest.fail("the server never reported that it started")

        token = load_token(data_dir)
        assert token
        auth = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        # No proxy from the environment: the request must reach this port, nothing else.
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
            assert http.get("/api/health").json() == {"version": labhq.__version__}
            assert http.post("/mcp", json=INIT, headers=auth).status_code == 200
            assert http.post("/mcp", json=INIT, headers=MCP_HEADERS).status_code == 401
            assert http.get("/api/anything").status_code == 404

        server.send_signal(signal.SIGTERM)
        _, stderr = server.communicate(timeout=DEADLINE_SECONDS)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()

    assert server.returncode == 0, stderr


async def test_a_mounted_app_that_crashes_on_startup_stops_the_api() -> None:
    async def crashing(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        raise RuntimeError("no task group")

    async def refusing(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "lifespan.startup.failed", "message": "port in use"})

    with pytest.raises(RuntimeError, match="no task group"):
        async with asgi_lifespan(crashing)(None):  # type: ignore[arg-type]
            pass
    with pytest.raises(LifespanError, match="port in use"):
        async with asgi_lifespan(refusing)(None):  # type: ignore[arg-type]
            pass
