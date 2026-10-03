"""Turn-end detection, the signal command and the CI guard for tmux."""

import io
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from labhq.adapters.tmux import TmuxMissingError, TmuxServer
from labhq.adapters.tmux.agents import TurnEnd, default_kinds
from labhq.adapters.tmux.server import config_text
from labhq.adapters.tmux.signal import main as signal_main
from labhq.adapters.tmux.turns import Watch, screen_delta, turn_ended
from tests.adapters.tmux.conftest import fake_kind, require_tmux

REPO_ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
QUIET = timedelta(seconds=5)


def test_quiescence_needs_output_and_then_silence() -> None:
    gemini = default_kinds.get("gemini")
    assert gemini.turn_end is TurnEnd.QUIESCENCE
    blank = Watch(screen="", last_change_at=T0)
    talked = Watch(screen="done", last_change_at=T0, changed=True)

    assert not turn_ended(blank, gemini, T0 + timedelta(minutes=5), QUIET)
    assert not turn_ended(talked, gemini, T0 + timedelta(seconds=4), QUIET)
    assert turn_ended(talked, gemini, T0 + timedelta(seconds=5), QUIET)


def test_a_signal_ends_the_turn_for_signalling_agents_only() -> None:
    signalled = Watch(screen="x", last_change_at=T0, changed=True, signal="{}")

    assert turn_ended(signalled, default_kinds.get("codex"), T0, QUIET)
    assert not turn_ended(signalled, default_kinds.get("aider"), T0, QUIET)


def test_a_pattern_ends_the_turn_on_a_whole_line() -> None:
    kind = fake_kind("fake", hook=False)

    assert turn_ended(Watch("a\nLABHQ-FAKE-TURN-END\n", T0), kind, T0, QUIET)
    assert not turn_ended(Watch("echo LABHQ-FAKE-TURN-END later", T0), kind, T0, QUIET)


def test_screen_deltas_are_the_new_and_changed_lines() -> None:
    assert screen_delta("a\nb", "a\nB\nc") == ["B", "c"]
    assert screen_delta("", "a") == ["a"]


def test_the_signal_command_writes_the_appended_payload(tmp_path: Path) -> None:
    target = tmp_path / "turn-end.json"
    payload = json.dumps({"type": "agent-turn-complete", "thread-id": "t-1"})

    assert signal_main(["turn", str(target), payload]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["thread-id"] == "t-1"


def test_the_signal_command_reads_stdin_and_prints_the_statusline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "statusline.json"
    monkeypatch.setattr("sys.stdin", io.StringIO('{"cost": {"total_cost_usd": 0.1}}'))

    assert signal_main(["statusline", str(target)]) == 0
    assert capsys.readouterr().out.strip() == "labhq"
    assert "total_cost_usd" in target.read_text(encoding="utf-8")


def test_the_signal_command_rejects_unknown_channels(tmp_path: Path) -> None:
    assert signal_main(["other", str(tmp_path / "x")]) == 2


def test_the_server_configuration_empties_update_environment() -> None:
    assert 'set-option -g update-environment ""' in config_text().splitlines()


def test_a_missing_tmux_is_an_error_not_a_silent_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(TmuxMissingError):
        TmuxServer(socket="labhq-test", state_dir=tmp_path)


def test_without_tmux_the_tmux_tests_fail_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(pytest.fail.Exception, match="tmux is not installed"):
        require_tmux()


def test_ci_installs_tmux_before_the_tests() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    install, tests = (
        workflow.find("apt-get install -y tmux"),
        workflow.find("run: uv run --frozen pytest"),
    )

    assert 0 < install < tests


def test_no_tmux_test_skips() -> None:
    others = [path for path in Path(__file__).parent.glob("*.py") if path != Path(__file__)]
    markers = ("pytest.skip(", "mark.skip", "importorskip")

    assert others
    for path in others:
        text = path.read_text(encoding="utf-8")
        assert not any(marker in text for marker in markers), path.name
