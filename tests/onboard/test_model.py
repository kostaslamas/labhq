import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from labhq.clock import FakeClock
from labhq.onboard import OnboardContext, OnboardSettings, PlatformInfo
from labhq.onboard.model import (
    CONSUMER_TERMS,
    LEGAL_AND_COMPLIANCE,
    NOTICE_FILENAME,
    ModelLoginStep,
    claude_logged_in,
)
from labhq.settings import Settings
from tests.onboard.conftest import install
from tools.guards import credential_refs

REPO = Path(__file__).resolve().parents[2]


def fake_claude(bin_dir: Path, answer: str) -> str:
    body = f"#!{sys.executable}\nimport sys\nassert sys.argv[1:] == ['auth', 'status', '--json']\n"
    body += f"print({answer!r})\n"
    return str(install(bin_dir, "claude", body))


def context(tmp_path: Path, **overrides: object) -> tuple[OnboardContext, list[str]]:
    lines: list[str] = []
    values: dict[str, object] = {
        "settings": Settings(data_dir=tmp_path),
        "onboard": OnboardSettings(),
        "clock": FakeClock(datetime(2026, 10, 3, tzinfo=UTC)),
        "platform": PlatformInfo("linux", "x86_64"),
        "environ": {},
        "which": lambda name: None,
        "say": lines.append,
    }
    values.update(overrides)
    return OnboardContext(**values), lines  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param(
            '{"loggedIn": true, "authMethod": "x"}',
            True,
            marks=pytest.mark.posix_only("the fake claude is a shebang script"),
        ),
        ('{"loggedIn": false}', False),
        ("not json", False),
        ('["loggedIn"]', False),
    ],
)
def test_only_the_logged_in_answer_counts(tmp_path: Path, answer: str, expected: bool) -> None:
    assert claude_logged_in(fake_claude(tmp_path, answer), timeout=10) is expected


def test_an_api_key_is_enough_without_running_claude(tmp_path: Path) -> None:
    probe, _ = context(tmp_path, environ={"ANTHROPIC_API_KEY": "set"})

    detection = ModelLoginStep().detect(probe)

    assert detection.present
    assert "API billing" in detection.detail


@pytest.mark.posix_only("the fake claude is a shebang script")
def test_a_logged_in_claude_verifies(tmp_path: Path) -> None:
    binary = fake_claude(tmp_path, '{"loggedIn": true}')
    probe, _ = context(tmp_path, which={"claude": binary}.get)

    assert ModelLoginStep().verify(probe).summary.startswith("Claude Code is logged in")


def test_a_missing_login_is_a_manual_action_not_a_failure(tmp_path: Path) -> None:
    probe, _ = context(tmp_path, which={"claude": fake_claude(tmp_path, '{"loggedIn": false}')}.get)
    step = ModelLoginStep()

    action = step.manual(probe, step.detect(probe))

    assert not step.required
    assert action is not None and "ANTHROPIC_API_KEY" in action.instruction


def test_the_notice_is_shown_once_and_recorded(tmp_path: Path) -> None:
    probe, lines = context(tmp_path)
    step = ModelLoginStep()

    step.automate(probe)
    step.automate(probe)

    (notice,) = lines
    assert CONSUMER_TERMS in notice and LEGAL_AND_COMPLIANCE in notice
    assert (tmp_path / NOTICE_FILENAME).read_text() == "2026-10-03T00:00:00+00:00\n"


def test_onboarding_passes_the_credential_reference_guard() -> None:
    assert credential_refs.main([str(REPO / "src" / "labhq" / "onboard")]) == 0
