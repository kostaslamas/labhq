"""Onboarding: from an empty data directory to a working system with no third-party account."""

from labhq.onboard.base import (
    Detection,
    ManualAction,
    OnboardContext,
    Outcome,
    Step,
    StepError,
)
from labhq.onboard.platforms import PlatformInfo, cloudflared_install_command, detect_platform
from labhq.onboard.probes import probes
from labhq.onboard.qr import render_qr
from labhq.onboard.registry import StepRegistry
from labhq.onboard.runner import OnboardError, StepReport, describe, run_steps
from labhq.onboard.settings import OnboardSettings
from labhq.onboard.steps import default_steps

__all__ = [
    "Detection",
    "ManualAction",
    "OnboardContext",
    "OnboardError",
    "OnboardSettings",
    "Outcome",
    "PlatformInfo",
    "Step",
    "StepError",
    "StepRegistry",
    "StepReport",
    "cloudflared_install_command",
    "default_steps",
    "describe",
    "detect_platform",
    "probes",
    "render_qr",
    "run_steps",
]
