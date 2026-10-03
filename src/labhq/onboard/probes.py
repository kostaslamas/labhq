"""What onboarding reports as already there before it changes anything.

A probe only looks; it never sets anything up. Steps that act register in `steps`.
"""

from collections.abc import Callable

from labhq.approvals.registry import Registry
from labhq.onboard.base import OnboardContext

type Probe = Callable[[OnboardContext], str]

DISCORD_TOKEN_VARIABLE = "LABHQ_DISCORD_TOKEN"


def _binary(name: str) -> Probe:
    def probe(context: OnboardContext) -> str:
        path = context.which(name)
        return f"at {path}" if path else "not found"

    return probe


def _discord(context: OnboardContext) -> str:
    return "configured" if context.environ.get(DISCORD_TOKEN_VARIABLE) else "not configured"


probes: Registry[Probe] = Registry("onboarding probe")
probes.register("cloudflared", _binary("cloudflared"))
probes.register("tailscale", _binary("tailscale"))
probes.register("Discord token", _discord)


def report(context: OnboardContext, registry: Registry[Probe] = probes) -> str:
    return "; ".join(f"{name} {registry.get(name)(context)}" for name in registry)
