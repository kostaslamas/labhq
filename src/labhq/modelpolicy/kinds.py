"""Which agent kinds take a model from the policy: the Claude family only.

A kind is `labhq.usage.plan.agent_kind`: the SDK adapter's key, or the CLI name of a tmux
agent. Any other kind ignores the policy row and says so in the run's events.
"""

MODEL_KINDS: set[str] = {"claude", "claude-code"}


def takes_model(kind: str) -> bool:
    return kind in MODEL_KINDS
