import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

READY_LINE = "Application startup complete"
DEADLINE_SECONDS = 60


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def labhq(*args: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "labhq", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT], ids=["sigterm", "sigint"])
def test_a_stop_signal_ends_labhq_serve_with_exit_code_zero(tmp_path: Path, stop: int) -> None:
    env = {
        **os.environ,
        "LABHQ_DATA_DIR": str(tmp_path / "data"),
        "PYTHONUNBUFFERED": "1",
    }
    env.pop("LABHQ_DATABASE_URL", None)
    init = labhq("init", env=env)
    init.communicate(timeout=DEADLINE_SECONDS)
    assert init.returncode == 0

    server = labhq("serve", "--port", str(free_port()), env=env)
    try:
        assert server.stderr is not None
        for line in server.stderr:
            if READY_LINE in line:
                break
        else:
            pytest.fail("the server never reported that it started")

        server.send_signal(stop)
        _, stderr = server.communicate(timeout=DEADLINE_SECONDS)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()

    assert server.returncode == 0, stderr
