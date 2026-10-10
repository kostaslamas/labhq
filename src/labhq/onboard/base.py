"""The onboarding contract: each step detects, automates, asks the owner, then verifies."""

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Protocol

from labhq.clock import Clock
from labhq.onboard.platforms import PlatformInfo
from labhq.onboard.settings import OnboardSettings
from labhq.settings import Settings


class StepError(RuntimeError):
    """A step could not finish; the message tells the owner what failed, never a secret."""


@dataclass(frozen=True)
class Detection:
    """What already exists. `present` is False when the step still has something to set up."""

    present: bool
    detail: str


@dataclass(frozen=True)
class ManualAction:
    """One thing only the owner can do, with a ready link and, for a phone, a QR code."""

    instruction: str
    link: str | None = None
    qr: bool = False


@dataclass(frozen=True)
class Outcome:
    """A verified step. A `link` is printed at the end under `label`, as a QR when `qr`."""

    summary: str
    label: str | None = None
    link: str | None = None
    qr: bool = False


class LocalServer(Protocol):
    def stop(self) -> None: ...


@dataclass
class OnboardContext:
    """What steps share. Steps set the fields later steps read; `resources` closes them all."""

    settings: Settings
    onboard: OnboardSettings
    clock: Clock
    platform: PlatformInfo
    environ: Mapping[str, str]
    which: Callable[[str], str | None]
    say: Callable[[str], None]
    # None runs non-interactively: a step that needs the owner fails instead of asking.
    confirm: Callable[[str], bool] | None = None
    # Asks a free-text question with a pre-filled answer; None when there is no terminal.
    ask: Callable[[str, str], str] | None = None
    # Optional steps the owner named (`labhq onboard discord`); such a step otherwise stays idle.
    offered: frozenset[str] = frozenset()
    resources: ExitStack = field(default_factory=ExitStack)
    token: str | None = None
    server: LocalServer | None = None
    public_url: str | None = None


class Step(Protocol):
    name: str
    # A required step must verify before onboarding says ready; an optional one may stay a
    # manual action for later.
    required: bool

    def detect(self, context: OnboardContext) -> Detection: ...

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        """What the owner must do first, or None when labhq can do the rest itself."""
        ...

    def automate(self, context: OnboardContext) -> None: ...

    def verify(self, context: OnboardContext) -> Outcome:
        """Prove the step works end to end; raises `StepError` otherwise."""
        ...
