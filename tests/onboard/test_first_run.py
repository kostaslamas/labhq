import importlib
import os
import re
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labhq.cli import app
from labhq.mcp.auth import TOKEN_FILENAME
from labhq.notify.topic import TOPIC_FILENAME
from labhq.onboard import render_qr
from labhq.onboard.model import CONSUMER_TERMS, LEGAL_AND_COMPLIANCE, NOTICE_FILENAME
from labhq.onboard.runner import OnboardError
from tests.cli.conftest import Cli, plain
from tests.onboard.conftest import Tunnel, onboard
from tests.onboard.fakes.ntfy import FakeNtfy

CONNECTOR_LINE = re.compile(r"^Connector URL: (\S+)$", re.MULTILINE)
READY = "labhq is ready."
COMMAND = importlib.import_module("labhq.cli.onboard")


def connector_url(output: str) -> str:
    (url,) = CONNECTOR_LINE.findall(output)
    return url


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_first_run_reaches_a_verified_system_without_any_account(
    tunnel: Tunnel, ntfy: FakeNtfy, cli: Cli, data_dir: Path
) -> None:
    result = onboard()

    assert result.exit_code == 0, result.output
    output = plain(result.output)
    token = (data_dir / TOKEN_FILENAME).read_text().strip()
    assert connector_url(output) == f"https://onboard-check.trycloudflare.com/mcp/{token}"
    assert "public URL: ok, https://onboard-check.trycloudflare.com answers `initialize`" in output
    assert output.rstrip().endswith(READY)
    # Migrated, and the test notification went out through the outbox.
    (row,) = cli.rows("SELECT kind, status FROM notifications")
    assert (row["kind"], row["status"].lower()) == ("onboard", "sent")
    topic = (data_dir / TOPIC_FILENAME).read_text().strip()
    assert [message["topic"] for message in ntfy.messages] == [topic]
    assert f"Subscribe in the ntfy app: {ntfy.url}/{topic}" in output
    # No account anywhere: the model login stays a suggestion for later, not a failure.
    assert "Later, model login:" in output


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_the_qr_code_encodes_exactly_the_printed_connector_url(
    tunnel: Tunnel, ntfy: FakeNtfy
) -> None:
    result = onboard()

    assert result.exit_code == 0, result.output
    output = plain(result.output)
    url = connector_url(output)
    assert f"Connector URL: {url}\n{render_qr(url)}\n" in output


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_a_second_run_keeps_token_topic_and_data_and_checks_again(
    tunnel: Tunnel, ntfy: FakeNtfy, cli: Cli, data_dir: Path
) -> None:
    assert onboard().exit_code == 0
    token = (data_dir / TOKEN_FILENAME).read_text()
    topic = (data_dir / TOPIC_FILENAME).read_text()

    second = onboard()

    assert second.exit_code == 0, second.output
    output = plain(second.output)
    assert "connector token: kept from an earlier run" in output
    assert "database: kept, schema at" in output
    assert (data_dir / TOKEN_FILENAME).read_text() == token
    assert (data_dir / TOPIC_FILENAME).read_text() == topic
    assert connector_url(output).endswith(token.strip())
    # The end-to-end check ran again: a second notification, the first row still there.
    assert len(ntfy.messages) == 2
    assert [r["status"].lower() for r in cli.rows("SELECT status FROM notifications")] == [
        "sent",
        "sent",
    ]
    assert output.rstrip().endswith(READY)


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_the_model_notice_appears_on_the_first_run_only(
    tunnel: Tunnel, ntfy: FakeNtfy, data_dir: Path
) -> None:
    first = plain(onboard().output)
    second = plain(onboard().output)

    assert CONSUMER_TERMS in first
    assert LEGAL_AND_COMPLIANCE in first
    assert "within your plan's terms" in first
    assert (data_dir / NOTICE_FILENAME).exists()
    assert CONSUMER_TERMS not in second
    assert LEGAL_AND_COMPLIANCE not in second


def test_onboard_error_names_the_step() -> None:
    assert str(OnboardError("public URL", "no answer")) == "public URL: no answer"


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_without_no_serve_the_program_takes_over_the_port_behind_the_same_tunnel(
    tunnel: Tunnel, ntfy: FakeNtfy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: list[tuple[str, int, bool]] = []

    def tunnel_pid() -> int:
        return int((tmp_path / "cloudflared.log").read_text().split("\n")[1])

    def fake_serve(*, host: str, port: int) -> None:
        # The check server has let go of the port, and the tunnel is still up.
        with socket.socket() as probe:
            probe.bind((host, port))
        served.append((host, port, process_is_alive(tunnel_pid())))

    monkeypatch.setattr(COMMAND, "serve", fake_serve)

    result = CliRunner().invoke(app, ["onboard", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert served == [("127.0.0.1", int(os.environ["LABHQ_ONBOARD_PORT"]), True)]
    assert not process_is_alive(tunnel_pid())


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.posix_only("the fake cloudflared is a /bin/sh wrapper")
def test_with_web_push_the_notifications_step_asks_for_a_device_instead_of_failing(
    tunnel: Tunnel, cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_NOTIFY_KIND", "webpush")

    result = onboard()

    assert result.exit_code == 0, result.output
    output = plain(result.output)
    assert "webpush is ready; no device has enabled it yet" in output
    assert "add it to the Home Screen first" in output
    assert cli.rows("SELECT kind FROM notifications") == []
    assert output.rstrip().endswith(READY)
