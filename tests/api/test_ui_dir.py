import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from labhq.api import settings as api_settings
from labhq.api.settings import ApiSettings, default_ui_dir, ui_absent_reason

DEADLINE_SECONDS = 60
READY_LINE = "Application startup complete"


class FakeDistribution:
    def __init__(self, marker: str | None) -> None:
        self.marker = marker

    def read_text(self, name: str) -> str | None:
        return self.marker if name == api_settings.UI_ABSENT_MARKER else None


def test_an_installed_wheel_serves_its_packaged_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LABHQ_API_UI_DIR", raising=False)
    packaged = tmp_path / "labhq" / "web"
    monkeypatch.setattr(api_settings, "PACKAGED_UI_DIR", packaged)
    assert default_ui_dir() == api_settings.SOURCE_UI_DIR
    packaged.mkdir(parents=True)
    assert default_ui_dir() == packaged
    assert ApiSettings().ui_dir == packaged
    monkeypatch.setenv("LABHQ_API_UI_DIR", str(tmp_path / "elsewhere"))
    assert ApiSettings().ui_dir == tmp_path / "elsewhere"


def test_a_present_ui_needs_no_word(tmp_path: Path) -> None:
    assert ui_absent_reason(ApiSettings(ui_dir=tmp_path)) is None


def test_a_python_only_wheel_says_why_the_ui_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_settings, "distribution", lambda _: FakeDistribution("skipped\n"))
    reason = ui_absent_reason(ApiSettings(ui_dir=tmp_path / "web"))
    assert reason is not None
    assert "the web UI is absent" in reason
    assert "LABHQ_SKIP_WEB_BUILD=1" in reason


def test_a_checkout_without_a_build_names_the_missing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_settings, "distribution", lambda _: FakeDistribution(None))
    reason = ui_absent_reason(ApiSettings(ui_dir=tmp_path / "web"))
    assert reason is not None
    assert str(tmp_path / "web") in reason


def labhq_process(*args: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "labhq", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_labhq_serve_says_the_ui_is_absent(tmp_path: Path) -> None:
    env = {**os.environ, "LABHQ_DATA_DIR": str(tmp_path / "data"), "PYTHONUNBUFFERED": "1"}
    env.pop("LABHQ_DATABASE_URL", None)
    env["LABHQ_API_UI_DIR"] = str(tmp_path / "no-ui")
    init = labhq_process("init", env=env)
    init.communicate(timeout=DEADLINE_SECONDS)
    assert init.returncode == 0

    # Port 0: the kernel picks a free one; this test never connects.
    server = labhq_process("serve", "--port", "0", env=env)
    seen: list[str] = []
    try:
        assert server.stderr is not None
        for line in server.stderr:
            seen.append(line)
            if READY_LINE in line:
                break
        server.send_signal(signal.SIGTERM)
        server.communicate(timeout=DEADLINE_SECONDS)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()

    assert any("the web UI is absent" in line for line in seen), seen
