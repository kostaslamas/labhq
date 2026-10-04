"""`labhq serve --expose`: the whole program behind a tunnel, not only the MCP server."""

import importlib
import os
import signal
import socket
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from labhq.cli import app
from labhq.expose import ExposureError, verify_connector
from labhq.mcp.auth import load_token

# `labhq.cli.serve` the module is shadowed by the command of the same name in the package.
serve_command = importlib.import_module("labhq.cli.serve")
PUBLIC = "https://quiet-river-demo.trycloudflare.com"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def initialised(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    monkeypatch.setenv("LABHQ_API_UI_DIR", str(data_dir.parent / "no-ui"))
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    return data_dir


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_serve_expose_prints_the_public_url_and_serves_the_full_program(
    initialised: Path, fake_cloudflared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = free_port()
    seen: dict[str, object] = {}
    announce = serve_command._announce

    def proof(url: str, secret: str) -> None:
        # The public name is not reachable from a test; prove the local server it fronts.
        verify_connector(f"http://127.0.0.1:{port}", secret)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
            seen["health"] = http.get("/api/health").status_code

    def announce_then_stop(url: str, secret: str) -> None:
        announce(url, secret)
        # Ctrl-C stand-in: the program stops on SIGTERM and exits 0.
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(serve_command, "_is_terminal", lambda: True)
    monkeypatch.setattr(serve_command, "verify_connector", proof)
    monkeypatch.setattr(serve_command, "_announce", announce_then_stop)

    result = CliRunner().invoke(app, ["serve", "--port", str(port), "--expose", "quick-tunnel"])

    assert result.exit_code == 0, result.output
    secret = load_token(initialised)
    assert result.stdout.count("Connector URL:") == 1
    assert f"Connector URL: {PUBLIC}/mcp/{secret}" in result.stdout
    assert seen["health"] == 200
    assert "tunnel --config /dev/null" in fake_cloudflared.read_text()


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_serve_expose_that_cannot_be_proved_stops_the_program_and_prints_no_url(
    initialised: Path, fake_cloudflared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(url: str, secret: str) -> None:
        raise ExposureError("the public URL did not answer")

    monkeypatch.setattr(serve_command, "verify_connector", refuse)

    result = CliRunner().invoke(
        app, ["serve", "--port", str(free_port()), "--expose", "quick-tunnel"]
    )

    assert result.exit_code != 0
    assert "the public URL did not answer" in result.stderr
    assert "Connector URL" not in result.stdout


def test_serve_expose_with_an_unknown_name_lists_the_available_ones(initialised: Path) -> None:
    result = CliRunner().invoke(app, ["serve", "--expose", "carrier-pigeon"])

    assert result.exit_code != 0
    assert "quick-tunnel" in result.stderr


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_off_a_terminal_the_token_never_reaches_stdout(
    initialised: Path, fake_cloudflared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = free_port()
    announce = serve_command._announce

    def announce_then_stop(url: str, token: str) -> None:
        announce(url, token)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(serve_command, "_is_terminal", lambda: False)
    monkeypatch.setattr(
        serve_command,
        "verify_connector",
        lambda url, s: verify_connector(f"http://127.0.0.1:{port}", s),
    )
    monkeypatch.setattr(serve_command, "_announce", announce_then_stop)

    result = CliRunner().invoke(app, ["serve", "--port", str(port), "--expose", "quick-tunnel"])

    assert result.exit_code == 0, result.output
    secret = load_token(initialised)
    assert secret
    assert secret not in result.stdout + result.stderr
    assert f"Connector URL: {PUBLIC}/mcp/ (run `labhq mcp token` to see the token)" in result.stdout


def test_the_local_url_is_withheld_the_same_way(
    initialised: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = load_token(initialised) or "x"
    shown: list[str] = []
    monkeypatch.setattr(serve_command.typer, "echo", lambda text, **_: shown.append(str(text)))
    monkeypatch.setattr(serve_command, "_is_terminal", lambda: False)

    serve_command._announce(f"http://127.0.0.1:8787/mcp/{secret}", secret)

    assert shown == [
        "Connector URL: http://127.0.0.1:8787/mcp/ (run `labhq mcp token` to see the token)"
    ]
