import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labhq.cli import app
from labhq.expose import ExposureError, exposures
from labhq.expose.quick_tunnel import QuickTunnelAdapter, find_url, tunnel_command

from .conftest import install_fake, process_is_gone


def read_log(log: Path) -> tuple[str, int]:
    argv, pid = log.read_text().splitlines()
    return argv, int(pid)


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_runs_cloudflared_with_empty_config_and_parses_the_url(fake_cloudflared: Path) -> None:
    tunnel = QuickTunnelAdapter().open(8787)
    try:
        assert tunnel.url == "https://quiet-river-demo.trycloudflare.com"
    finally:
        tunnel.close()
    argv, _ = read_log(fake_cloudflared)
    assert argv == "tunnel --config /dev/null --url http://127.0.0.1:8787"


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_close_stops_cloudflared_and_is_repeatable(fake_cloudflared: Path) -> None:
    tunnel = QuickTunnelAdapter().open(8787)
    _, pid = read_log(fake_cloudflared)
    tunnel.close()
    tunnel.close()
    assert tunnel.process.poll() is not None
    assert process_is_gone(pid)


def test_quick_tunnel_is_registered() -> None:
    assert isinstance(exposures.get("quick-tunnel")(), QuickTunnelAdapter)


def test_command_always_carries_the_empty_config() -> None:
    command = tunnel_command("cloudflared", 9000)
    assert command[command.index("--config") + 1] == "/dev/null"


def test_find_url_ignores_other_hosts() -> None:
    assert find_url("see https://developers.cloudflare.com/ for docs") is None
    assert find_url("| https://a-b-c.trycloudflare.com |") == "https://a-b-c.trycloudflare.com"


def test_missing_cloudflared_fails_with_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ExposureError, match=r"not installed.*install"):
        QuickTunnelAdapter().open(8787)


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_exit_before_url_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake(tmp_path, monkeypatch, "#!{python}\nprint('boom')\n")
    with pytest.raises(ExposureError, match="exited before"):
        QuickTunnelAdapter().open(8787)


@pytest.mark.posix_only("the fake cloudflared is a shebang script that waits on signal.pause")
def test_no_url_in_time_is_a_timeout_and_stops_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = install_fake(
        tmp_path,
        monkeypatch,
        "#!{python}\nimport os, signal\n"
        "open(os.environ['FAKE_CLOUDFLARED_LOG'], 'w').write(str(os.getpid()))\n"
        "signal.pause()\n",
    )
    with pytest.raises(ExposureError, match=r"no trycloudflare\.com URL within 0\.3 seconds"):
        QuickTunnelAdapter(url_timeout=0.3).open(8787)
    assert process_is_gone(int(log.read_text()))


def test_cli_without_cloudflared_exits_non_zero_and_does_not_serve_locally(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])
    result = CliRunner().invoke(app, ["mcp", "serve", "--port", port, "--expose", "quick-tunnel"])
    assert result.exit_code != 0
    assert "cloudflared is not installed" in result.stderr
    assert "Connector URL" not in result.stdout


def test_cli_unknown_exposure_lists_the_available_ones(data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["mcp", "serve", "--expose", "carrier-pigeon"])
    assert result.exit_code != 0
    assert "quick-tunnel" in result.stderr
