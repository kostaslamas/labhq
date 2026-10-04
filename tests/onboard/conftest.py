import os
import socket
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from labhq.cli import app
from tests.cli.conftest import cli, data_dir
from tests.onboard.fakes import ntfy as fake_ntfy
from tests.onboard.fakes.certs import write_certificates

__all__ = ["cli", "data_dir"]

FAKES = Path(__file__).resolve().parent / "fakes"
# Anything that would let the developer's or CI's own setup leak into a run.
ISOLATED_PREFIXES = ("LABHQ_NOTIFY_", "LABHQ_ONBOARD_", "FAKE_TUNNEL_")
ISOLATED_NAMES = (
    "ANTHROPIC_API_KEY",
    "LABHQ_CLI_PATH",
    "LABHQ_DISCORD_TOKEN",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def install(bin_dir: Path, name: str, body: str) -> Path:
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No real binary, model login or notifier is reachable; returns the only PATH entry."""
    for name in list(os.environ):
        if name.startswith(ISOLATED_PREFIXES) or name in ISOLATED_NAMES:
            monkeypatch.delenv(name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    # These tests exercise the ntfy channel; Web Push has its own onboarding test.
    monkeypatch.setenv("LABHQ_NOTIFY_KIND", "ntfy")
    monkeypatch.setenv("LABHQ_ONBOARD_PORT", str(free_port()))
    monkeypatch.setenv("LABHQ_ONBOARD_VERIFY_ATTEMPTS", "3")
    monkeypatch.setenv("LABHQ_ONBOARD_VERIFY_DELAY_SECONDS", "0.2")
    return bin_dir


@pytest.fixture(scope="session")
def certificates(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("certs")
    write_certificates(directory)
    return directory


@dataclass
class Tunnel:
    monkeypatch: pytest.MonkeyPatch

    def silent(self) -> None:
        """Prints its URL but answers nothing: the public URL check must fail."""
        self.monkeypatch.setenv("FAKE_TUNNEL_MODE", "silent")


@pytest.fixture
def tunnel(
    isolated: Path, certificates: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Tunnel:
    """A fake `cloudflared` on PATH that really tunnels, over TLS trusted through a test CA."""
    install(
        isolated,
        "cloudflared",
        f'#!/bin/sh\nexec "{sys.executable}" "{FAKES}/cloudflared.py" "$@"\n',
    )
    proxy = f"http://127.0.0.1:{free_port()}"
    monkeypatch.setenv("FAKE_TUNNEL_PROXY_PORT", proxy.rsplit(":", 1)[1])
    monkeypatch.setenv("FAKE_TUNNEL_CERTS", str(certificates))
    monkeypatch.setenv("FAKE_CLOUDFLARED_LOG", str(tmp_path / "cloudflared.log"))
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, proxy)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    monkeypatch.setenv("SSL_CERT_FILE", str(certificates / "ca.pem"))
    return Tunnel(monkeypatch)


@pytest.fixture
def ntfy(monkeypatch: pytest.MonkeyPatch) -> Iterator[fake_ntfy.FakeNtfy]:
    server = fake_ntfy.start()
    monkeypatch.setenv("LABHQ_NOTIFY_NTFY_SERVER", server.url)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def onboard(*args: str, input: str | None = None) -> Result:
    """`labhq onboard` without serving, non-interactive unless `input` answers the prompts."""
    flags = ["--no-serve"] if input is not None else ["--no-serve", "--non-interactive"]
    return CliRunner().invoke(app, ["onboard", *flags, *args], input=input)
