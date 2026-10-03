"""Run the registered steps in order. The runner knows the contract, never a step's name."""

from collections.abc import Iterable
from dataclasses import dataclass

from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, Step, StepError
from labhq.onboard.qr import render_qr


class OnboardError(RuntimeError):
    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


@dataclass(frozen=True)
class StepReport:
    name: str
    detection: Detection
    # Exactly one is set: a verified outcome, or a manual action left for later.
    outcome: Outcome | None = None
    later: ManualAction | None = None


def describe(action: ManualAction) -> list[str]:
    lines = [action.instruction]
    if action.link is not None:
        lines.append(action.link)
        if action.qr:
            lines.append(render_qr(action.link))
    return lines


def _ask_owner(step: Step, context: OnboardContext, action: ManualAction) -> Detection:
    """Show the action until it is done; returns the fresh detection. Raises if it is not."""
    while True:
        context.say(f"{step.name}: one step for you:")
        for line in describe(action):
            context.say(f"  {line}")
        if context.confirm is None or not context.confirm(f"Done with {step.name}?"):
            raise OnboardError(step.name, action.instruction)
        detection = step.detect(context)
        next_action = step.manual(context, detection)
        if next_action is None:
            return detection
        action = next_action


def run_step(step: Step, context: OnboardContext) -> StepReport:
    detection = step.detect(context)
    context.say(f"{step.name}: {detection.detail}")
    action = step.manual(context, detection)
    try:
        if action is not None and step.required:
            detection = _ask_owner(step, context, action)
            action = None
        step.automate(context)
        if action is not None:
            return StepReport(step.name, detection, later=action)
        outcome = step.verify(context)
    except StepError as error:
        raise OnboardError(step.name, str(error)) from error
    context.say(f"{step.name}: ok, {outcome.summary}")
    return StepReport(step.name, detection, outcome=outcome)


def run_steps(steps: Iterable[Step], context: OnboardContext) -> list[StepReport]:
    """Every step in order; the first failure stops onboarding with that step named."""
    return [run_step(step, context) for step in steps]
