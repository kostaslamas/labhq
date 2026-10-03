import importlib
import os
from pathlib import Path

import pytest

from labhq.onboard import PlatformInfo
from tests.cli.conftest import Cli, plain
from tests.onboard.conftest import Tunnel, onboard
from tests.onboard.fakes.ntfy import FakeNtfy
from tests.onboard.fakes.ntfy import start as start_ntfy

READY = "labhq is ready."
# The package re-exports the command under the module's own name, so patch the module object.
COMMAND = importlib.import_module("labhq.cli.onboard")


def test_a_tunnel_that_does_not_answer_fails_on_the_public_url_step(
    tunnel: Tunnel, ntfy: FakeNtfy, tmp_path: Path
) -> None:
    tunnel.silent()

    result = onboard()

    assert result.exit_code != 0
    assert "error: public URL: the public URL did not answer `initialize`" in plain(result.output)
    assert READY not in result.output
    assert "Connector URL:" not in result.output
    assert ntfy.messages == []
    # The tunnel was stopped, not left public.
    pid = int((tmp_path / "cloudflared.log").read_text().split("\n")[1])
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_notification_ntfy_rejects_fails_on_the_notifications_step(
    tunnel: Tunnel, cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejecting = start_ntfy(status=500)
    monkeypatch.setenv("LABHQ_NOTIFY_NTFY_SERVER", rejecting.url)
    try:
        result = onboard()
    finally:
        rejecting.shutdown()
        rejecting.server_close()

    assert result.exit_code != 0
    output = plain(result.output)
    assert "error: notifications: the test notification was not accepted" in output
    assert "HTTP 500" in output
    assert READY not in output
    # Not left pending for the program to retry later.
    (row,) = cli.rows("SELECT status FROM notifications")
    assert row["status"].lower() == "failed"


PLATFORMS = {
    "macos": (PlatformInfo("darwin", "arm64"), "brew install cloudflared"),
    "windows": (
        PlatformInfo("win32", "AMD64"),
        "winget install --id Cloudflare.cloudflared",
    ),
    "debian": (
        PlatformInfo("linux", "x86_64", {"ID": "ubuntu", "ID_LIKE": "debian"}),
        "cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb",
    ),
    "rpm": (
        PlatformInfo("linux", "aarch64", {"ID": "fedora"}),
        "cloudflared-linux-aarch64.rpm && sudo rpm -i cloudflared.rpm",
    ),
}


@pytest.mark.parametrize("name", sorted(PLATFORMS))
def test_a_missing_cloudflared_is_one_manual_step_with_the_platform_command(
    name: str, ntfy: FakeNtfy, monkeypatch: pytest.MonkeyPatch
) -> None:
    info, command = PLATFORMS[name]
    monkeypatch.setattr(COMMAND, "detect_platform", lambda: info)

    result = onboard()

    assert result.exit_code != 0
    output = plain(result.output)
    assert "public URL: cloudflared not found" in output
    assert output.count("one step for you") == 1
    assert command in output
    assert "error: public URL: Install cloudflared: " in output
    # No silent fall back to a local-only server, and nothing after the failed step ran.
    assert READY not in output
    assert "Connector URL:" not in output
    assert ntfy.messages == []


def test_interactive_onboarding_asks_once_and_stops_when_the_owner_declines(
    ntfy: FakeNtfy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(COMMAND, "detect_platform", lambda: PLATFORMS["macos"][0])

    result = onboard(input="n\n")

    assert result.exit_code != 0
    assert "Done with public URL?" in result.output
    assert READY not in result.output
