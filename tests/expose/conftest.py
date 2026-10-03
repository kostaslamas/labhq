import os
import stat
import sys
from pathlib import Path

import pytest

FAKE_CLOUDFLARED = """#!{python}
import os
import signal
import sys

with open(os.environ["FAKE_CLOUDFLARED_LOG"], "w") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n" + str(os.getpid()) + "\\n")
sys.stderr.write("2026-10-03T10:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...\\n")
sys.stderr.write("2026-10-03T10:00:01Z INF |  https://quiet-river-demo.trycloudflare.com  |\\n")
sys.stderr.flush()
signal.pause()
"""


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(path))
    return path


def install_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    """Put a fake `cloudflared` alone on PATH; returns the file it logs its argv and pid to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "cloudflared"
    script.write_text(body.replace("{python}", sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "cloudflared.log"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("FAKE_CLOUDFLARED_LOG", str(log))
    return log


@pytest.fixture
def fake_cloudflared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return install_fake(tmp_path, monkeypatch, FAKE_CLOUDFLARED)


def process_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False
