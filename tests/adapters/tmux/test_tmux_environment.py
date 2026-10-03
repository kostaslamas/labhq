"""No credential reaches a worker in the private tmux server (ADR 0003, ADR 0001)."""

import subprocess
import sys
from pathlib import Path

import pytest

from labhq.adapters import RunRequest
from labhq.adapters.contract import run_once
from labhq.adapters.tmux import TmuxServer
from tests.adapters.tmux.conftest import AdapterMaker, agent_config

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")

SECRETS = {
    "SSH_AUTH_SOCK": "/tmp/agent.sock",
    "GH_TOKEN": "gh-secret",
    "GITHUB_TOKEN": "github-secret",
    "LABHQ_CLIENT_ONLY": "client-secret",
}
HELPER = '"!f() { echo username=u; echo password=leaked; }; f"'


@pytest.fixture
def leaky_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Credentials in every place a worker could inherit them from."""
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    # A helper in the user's global config, and one injected through the environment.
    home = Path(tmp_path / "home")
    (home / ".gitconfig").write_text(f"[credential]\n\thelper = {HELPER}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", HELPER.strip('"'))


@pytest.mark.usefixtures("leaky_environment")
async def test_a_worker_sees_no_credentials_even_when_the_caller_has_them(
    make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    request = RunRequest(prompt="ENV", cwd=tmp_path, config=agent_config())

    events, _ = await run_once(make_adapter(), request)

    screen = "\n".join(line for event in events for line in event.payload.get("lines", []))
    for name in SECRETS:
        assert f"env {name}=-" in screen
    assert "credential=none" in screen
    assert "leaked" not in screen.replace("credential=none", "")


@pytest.mark.usefixtures("leaky_environment")
def test_the_global_helper_would_answer_outside_the_worker(tmp_path: Path) -> None:
    # The fixture is real: the same git, run with the caller's environment, leaks.
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=example.invalid\n\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert "password=leaked" in result.stdout


def test_a_variable_only_in_the_clients_environment_stays_out_of_the_session(
    tmux_server: TmuxServer, tmp_path: Path
) -> None:
    # Bypass the allowlist for this one client, as an owner's own tmux client would not:
    # `update-environment` is empty, so tmux copies nothing from the client into the session.
    client = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SSH_AUTH_SOCK": "/tmp/s.sock"}
    tmux_server.ensure_started()
    tmux_server.new_session(
        "probe",
        cwd=tmp_path,
        argv=[sys.executable, "-c", "import os; print('sock', os.environ.get('SSH_AUTH_SOCK'))"],
        variables={"LABHQ_PROBE": "1"},
        client_env=client,
    )

    # The pane stays after the process exits (remain-on-exit); poll its state, not a timer.
    for _ in range(1000):
        if tmux_server.pane_state("probe").dead:
            break
    assert tmux_server.pane_state("probe").dead
    assert "sock None" in tmux_server.capture("probe")
    assert "SSH_AUTH_SOCK" not in tmux_server.show_environment("probe")
    assert tmux_server.show_environment("probe")["LABHQ_PROBE"] == "1"
    assert tmux_server.run("show-options", "-gv", "update-environment").strip() == ""


def test_the_server_is_private_and_configured_by_labhq(tmux_server: TmuxServer) -> None:
    tmux_server.ensure_started()

    assert tmux_server.socket.startswith("labhq-test-")
    assert tmux_server.config_path.read_text(encoding="utf-8").count("update-environment") == 1
    assert tmux_server.run("show-options", "-gv", "remain-on-exit").strip() == "on"
