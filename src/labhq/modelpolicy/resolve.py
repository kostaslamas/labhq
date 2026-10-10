"""Resolution order: request, agent, task kind, role, then the tool's own default.

An explicit model on the request is the caller's decision and is used as given. The agent
override and the policy rows are skipped when the plan check says the account cannot use
that model; the skip is kept so the run can say which row was used and why.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from labhq.modelpolicy.policy import ModelPolicy, PolicyRow

log = logging.getLogger(__name__)

TOOL_DEFAULT = "tool_default"


@dataclass(frozen=True)
class Skip:
    source: str
    model: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    model: str | None
    effort: str | None
    max_output_tokens: int | None
    source: str
    skipped: tuple[Skip, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict[str, object]:
        return {
            "model": self.model,
            "effort": self.effort,
            "source": self.source,
            "skipped": [vars(skip) for skip in self.skipped],
        }


def resolve(
    policy: ModelPolicy,
    *,
    request_model: str | None,
    agent_model: str | None,
    task_kind: str | None,
    role: str | None,
    unusable: Mapping[str, str],
) -> Resolution:
    kind_row, role_row = policy.row(task_kind), policy.row(role)
    candidates: list[tuple[str, str | None, PolicyRow | None]] = [
        ("request", request_model, None),
        ("agent", agent_model, None),
        (f"task_kind:{task_kind}", kind_row.model if kind_row else None, kind_row),
        (f"role:{role}", role_row.model if role_row else None, role_row),
    ]
    skipped: list[Skip] = []
    for source, model, row in candidates:
        if not model:
            continue
        reason = unusable.get(model)
        if reason is not None and source != "request":
            log.info("model row %s skipped: %s cannot be used (%s)", source, model, reason)
            skipped.append(Skip(source, model, reason))
            continue
        # Effort and the output cap follow the policy even when the model was chosen higher up.
        effort_row = row or kind_row or role_row
        return Resolution(
            model,
            effort_row.effort if effort_row else None,
            effort_row.max_output_tokens if effort_row else None,
            source,
            tuple(skipped),
        )
    return Resolution(None, None, None, TOOL_DEFAULT, tuple(skipped))
