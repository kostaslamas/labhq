import ast
import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from labhq.clock import FakeClock
from labhq.onboard import (
    Detection,
    ManualAction,
    OnboardContext,
    OnboardError,
    OnboardSettings,
    Outcome,
    PlatformInfo,
    StepError,
    StepRegistry,
    default_steps,
    run_steps,
)
from labhq.onboard import runner as runner_module
from labhq.onboard.probes import probes, report
from labhq.settings import Settings


@dataclass
class FakeStep:
    name: str
    required: bool = True
    present: list[bool] = field(default_factory=lambda: [True])
    fail_verify: bool = False
    calls: list[str] = field(default_factory=list)

    def detect(self, context: OnboardContext) -> Detection:
        self.calls.append("detect")
        present = self.present.pop(0) if len(self.present) > 1 else self.present[0]
        return Detection(present, "there" if present else "missing")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None if detection.present else ManualAction(f"do {self.name}")

    def automate(self, context: OnboardContext) -> None:
        self.calls.append("automate")

    def verify(self, context: OnboardContext) -> Outcome:
        self.calls.append("verify")
        if self.fail_verify:
            raise StepError("it broke")
        return Outcome(f"{self.name} works", label=self.name, link=f"https://{self.name}.test")


def context(tmp_path: Path, *, answers: list[bool] | None = None) -> OnboardContext:
    lines: list[str] = []
    return OnboardContext(
        settings=Settings(data_dir=tmp_path),
        onboard=OnboardSettings(),
        clock=FakeClock(datetime(2026, 10, 3, tzinfo=UTC)),
        platform=PlatformInfo("linux", "x86_64"),
        environ={},
        which=lambda name: None,
        say=lines.append,
        confirm=None if answers is None else (lambda prompt: answers.pop(0)),
    )


def test_a_new_step_is_one_registration_and_runs_in_order(tmp_path: Path) -> None:
    steps = StepRegistry()
    late, early = FakeStep("late"), FakeStep("early")
    steps.register(late, order=20)
    steps.register(early, order=10)

    reports = run_steps(steps, context(tmp_path))

    assert [r.name for r in reports] == ["early", "late"]
    assert early.calls == ["detect", "automate", "verify"]
    assert reports[0].outcome == Outcome("early works", label="early", link="https://early.test")


def test_a_fake_step_slots_in_between_the_shipped_ones() -> None:
    steps = default_steps.copy()
    steps.register(FakeStep("chat"), order=45)

    names = [step.name for step in steps]

    assert names.index("notifications") < names.index("chat") < names.index("model login")
    assert "chat" not in default_steps


def test_a_name_registered_twice_is_refused() -> None:
    steps = StepRegistry()
    steps.register(FakeStep("same"), order=1)
    with pytest.raises(ValueError, match="already registered"):
        steps.register(FakeStep("same"), order=2)


def test_the_runner_never_names_a_step() -> None:
    names = {step.name for step in default_steps}
    literals = {
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(runner_module)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not names & literals


def test_a_failed_verify_names_the_step_and_stops(tmp_path: Path) -> None:
    steps = StepRegistry()
    after = FakeStep("after")
    steps.register(FakeStep("broken", fail_verify=True), order=1)
    steps.register(after, order=2)

    with pytest.raises(OnboardError) as caught:
        run_steps(steps, context(tmp_path))

    assert (caught.value.step, caught.value.reason) == ("broken", "it broke")
    assert after.calls == []


def test_a_required_manual_step_fails_without_prompting_when_non_interactive(
    tmp_path: Path,
) -> None:
    steps = StepRegistry()
    step = FakeStep("needs owner", present=[False])
    steps.register(step, order=1)

    with pytest.raises(OnboardError, match="needs owner: do needs owner"):
        run_steps(steps, context(tmp_path))
    assert "automate" not in step.calls


def test_interactive_onboarding_detects_again_after_the_owner_is_done(tmp_path: Path) -> None:
    steps = StepRegistry()
    step = FakeStep("needs owner", present=[False, True])
    steps.register(step, order=1)

    (report_,) = run_steps(steps, context(tmp_path, answers=[True]))

    assert report_.outcome is not None
    assert step.calls == ["detect", "detect", "automate", "verify"]


def test_an_optional_manual_step_is_left_for_later_and_not_verified(tmp_path: Path) -> None:
    steps = StepRegistry()
    step = FakeStep("optional", required=False, present=[False])
    steps.register(step, order=1)

    (report_,) = run_steps(steps, context(tmp_path))

    assert report_.outcome is None
    assert report_.later == ManualAction("do optional")
    assert step.calls == ["detect", "automate"]


def test_probes_report_cloudflared_tailscale_and_a_discord_token(tmp_path: Path) -> None:
    probing = context(tmp_path)
    probing.which = {"tailscale": "/usr/bin/tailscale"}.get
    probing.environ = {"LABHQ_DISCORD_TOKEN": "x"}

    line = report(probing)

    assert set(probes) == {"cloudflared", "tailscale", "Discord token"}
    assert "cloudflared not found" in line
    assert "tailscale at /usr/bin/tailscale" in line
    assert "Discord token configured" in line
