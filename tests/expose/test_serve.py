import socket
from pathlib import Path

import httpx
import pytest
from mcp.types import ToolAnnotations
from starlette.testclient import TestClient
from starlette.types import ASGIApp

from labhq.expose import ExposureError, open_verified, serve_exposed, verify_connector
from labhq.expose.quick_tunnel import QuickTunnelAdapter
from labhq.expose.verify import INITIALIZE
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import ToolRegistry, ToolSpec

from .conftest import process_is_gone

SECRET = "s3cret-token"
PUBLIC = "https://quiet-river-demo.trycloudflare.com"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def echo(text: str) -> str:
    return text


def make_app() -> ASGIApp:
    registry = ToolRegistry()
    registry.register(ToolSpec("echo", "Repeat.", ToolAnnotations(readOnlyHint=True), echo))
    return build_app(registry, SECRET)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def logged_pid(log: Path) -> int:
    return int(log.read_text().splitlines()[1])


def test_verify_passes_through_the_secret_path_with_an_initialize_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verify_connector(PUBLIC, SECRET, client=client)
    assert [str(r.url) for r in seen] == [f"{PUBLIC}/mcp/{SECRET}"]
    assert seen[0].read() == httpx.Request("POST", PUBLIC, json=INITIALIZE).read()


def test_verify_retries_then_fails_without_leaking_the_secret() -> None:
    delays: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    with pytest.raises(ExposureError) as caught:
        verify_connector(PUBLIC, SECRET, client=client, attempts=3, sleep=delays.append)
    assert len(delays) == 2
    assert "HTTP 502" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_verify_rejects_an_event_stream_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="data: {}", headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ExposureError):
        verify_connector(PUBLIC, SECRET, client=client, attempts=1)


def test_failed_proof_stops_the_tunnel_and_raises(fake_cloudflared: Path) -> None:
    def refuse(url: str, secret: str) -> None:
        raise ExposureError("refused")

    with pytest.raises(ExposureError, match="refused"):
        open_verified(QuickTunnelAdapter(), 8787, SECRET, verify=refuse)
    assert process_is_gone(logged_pid(fake_cloudflared))


def test_verify_against_the_app_accepts_only_the_right_secret() -> None:
    with TestClient(make_app(), base_url=PUBLIC) as client:
        verify_connector(PUBLIC, SECRET, client=client)
        with pytest.raises(ExposureError):
            verify_connector(PUBLIC, "wrong", client=client, attempts=1)


def test_running_server_answers_json_not_sse_and_the_url_is_announced_once(
    fake_cloudflared: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()
    announced: list[str] = []

    def announce(url: str) -> None:
        announced.append(url)
        local = f"http://127.0.0.1:{port}/mcp/{SECRET}"
        for method, params in (("initialize", INITIALIZE["params"]), ("tools/list", {})):
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            response = httpx.post(local, json=body, headers=HEADERS)
            assert response.headers["content-type"].startswith("application/json")
            assert "result" in response.json()
        raise KeyboardInterrupt  # stands in for Ctrl-C: tears everything down

    serve_exposed(
        make_app(),
        host="127.0.0.1",
        port=port,
        secret=SECRET,
        adapter=QuickTunnelAdapter(),
        announce=announce,
        verify=lambda url, secret: verify_connector(f"http://127.0.0.1:{port}", secret),
    )

    assert announced == [f"{PUBLIC}/mcp/{SECRET}"]
    assert process_is_gone(logged_pid(fake_cloudflared))
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_unverified_tunnel_never_announces(fake_cloudflared: Path) -> None:
    announced: list[str] = []

    def refuse(url: str, secret: str) -> None:
        raise ExposureError("the public URL did not answer")

    with pytest.raises(ExposureError):
        serve_exposed(
            make_app(),
            host="127.0.0.1",
            port=free_port(),
            secret=SECRET,
            adapter=QuickTunnelAdapter(),
            announce=announced.append,
            verify=refuse,
        )
    assert announced == []
    assert process_is_gone(logged_pid(fake_cloudflared))
