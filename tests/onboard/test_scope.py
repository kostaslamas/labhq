"""Onboarding asks which folder holds the projects, suggests one, and can be skipped."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from labhq.clock import SystemClock
from labhq.onboard import OnboardSettings, detect_platform
from labhq.onboard.base import OnboardContext
from labhq.onboard.scope import QUESTION, SessionScopeStep
from labhq.settings import Settings
from tests.cli.conftest import Cli


@dataclass
class Harness:
    context: OnboardContext
    said: list[str]
    code: Path


@pytest.fixture
def harness(cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    cli.ok("init")
    home = tmp_path / "home"
    code = home / "code"
    code.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    said: list[str] = []
    context = OnboardContext(
        settings=Settings(),
        onboard=OnboardSettings(),
        clock=SystemClock(),
        platform=detect_platform(),
        environ={},
        which=lambda name: None,
        say=said.append,
    )
    return Harness(context, said, code)


def stored(cli: Cli) -> list[str]:
    return [row["value"] for row in cli.rows("SELECT value FROM program_state")]


def test_the_question_is_pre_filled_with_the_first_existing_candidate(
    harness: Harness, cli: Cli
) -> None:
    asked: list[tuple[str, str]] = []

    def accept_the_suggestion(question: str, default: str) -> str:
        asked.append((question, default))
        return default

    harness.context.ask = accept_the_suggestion
    step = SessionScopeStep()

    step.automate(harness.context)

    assert asked == [(QUESTION, str(harness.code))]
    assert str(harness.code.resolve()) in stored(cli)[0]
    assert step.detect(harness.context).present
    assert "stays inside" in step.verify(harness.context).summary


def test_an_empty_answer_skips_and_the_scan_stays_machine_wide(harness: Harness, cli: Cli) -> None:
    harness.context.ask = lambda question, default: ""
    step = SessionScopeStep()

    step.automate(harness.context)

    assert stored(cli) == []
    assert "machine-wide" in step.verify(harness.context).summary


def test_without_a_terminal_nothing_is_asked_or_stored(harness: Harness, cli: Cli) -> None:
    harness.context.ask = None

    SessionScopeStep().automate(harness.context)

    assert stored(cli) == []


def test_a_bad_answer_is_explained_and_asked_again(harness: Harness, cli: Cli) -> None:
    answers = iter(["/", str(harness.code)])
    harness.context.ask = lambda question, default: next(answers)

    SessionScopeStep().automate(harness.context)

    assert any("root of a filesystem" in line for line in harness.said)
    assert len(stored(cli)) == 1


def test_a_scope_that_is_already_set_is_not_asked_about_again(harness: Harness, cli: Cli) -> None:
    cli.ok("sessions", "roots", "add", str(harness.code))

    def refuse(question: str, default: str) -> str:
        pytest.fail("asked although a scope exists")

    harness.context.ask = refuse

    SessionScopeStep().automate(harness.context)
