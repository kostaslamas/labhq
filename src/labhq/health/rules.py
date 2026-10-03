"""Rule types as a registry: `type -> evaluator`. A new type is a new registration.

Rules are `health_rules` rows; `type` names the evaluator and `params` is its input. An
evaluator only answers whether the rule is violated for a host. What follows a violation is
`labhq.health.incidents`' business, and nothing here ever fixes anything.
"""

import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import HealthRule, HealthSample, Host


@dataclass(frozen=True)
class RuleContext:
    session: AsyncSession
    rule: HealthRule
    host: Host
    now: datetime


@dataclass(frozen=True)
class Evaluation:
    violated: bool
    # Stored on the incident a violation opens: what was seen, so a reader needs no query.
    details: dict[str, Any] = field(default_factory=dict)


Evaluator = Callable[[RuleContext], Awaitable[Evaluation]]


class UnknownRuleTypeError(LookupError):
    pass


class RuleRegistry:
    def __init__(self) -> None:
        self._evaluators: dict[str, Evaluator] = {}
        self._params: dict[str, type[BaseModel]] = {}

    def register(
        self, rule_type: str, params: type[BaseModel] | None = None
    ) -> Callable[[Evaluator], Evaluator]:
        """Register an evaluator; `params` lets rule management validate a rule before it lands."""

        def decorator(evaluator: Evaluator) -> Evaluator:
            if rule_type in self._evaluators:
                raise ValueError(f"rule type already registered: {rule_type}")
            self._evaluators[rule_type] = evaluator
            if params is not None:
                self._params[rule_type] = params
            return evaluator

        return decorator

    def types(self) -> frozenset[str]:
        return frozenset(self._evaluators)

    def validate_params(self, rule_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """The params as stored: validated by the type's model, defaults filled in.

        Raises `UnknownRuleTypeError` or pydantic's `ValidationError`. A type registered
        without a model takes its params as given.
        """
        if rule_type not in self._evaluators:
            raise UnknownRuleTypeError(rule_type)
        model = self._params.get(rule_type)
        if model is None:
            return dict(params)
        return model.model_validate(params).model_dump(mode="json")

    async def evaluate(self, context: RuleContext) -> Evaluation:
        try:
            evaluator = self._evaluators[context.rule.type]
        except KeyError:
            raise UnknownRuleTypeError(context.rule.type) from None
        return await evaluator(context)


registry = RuleRegistry()


_COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


class ThresholdParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str = Field(min_length=1)
    comparison: Literal[">", ">=", "<", "<="]
    value: float
    # How long the comparison must have held. Zero means the latest sample decides.
    duration_seconds: float = Field(default=0.0, ge=0)
    # Restricts the rule to one mount or sensor; None watches every subject of the metric.
    subject: str | None = None


def _same_subject(subject: str | None) -> ColumnElement[bool]:
    column = HealthSample.subject
    return column.is_(None) if subject is None else column == subject


async def _subjects(context: RuleContext, params: ThresholdParams) -> list[str | None]:
    if params.subject is not None:
        return [params.subject]
    rows = await context.session.scalars(
        select(HealthSample.subject)
        .where(HealthSample.host_id == context.host.id, HealthSample.metric == params.metric)
        .distinct()
    )
    return list(rows)


async def _held_throughout(
    context: RuleContext, params: ThresholdParams, subject: str | None
) -> list[float] | None:
    """The values seen over the window if every one violates, else None.

    A sample's value stands until the next sample, so the window [now - duration, now] is
    covered by the last sample at or before its start plus every sample inside it. Without
    a sample at the start the condition cannot be shown to have held long enough.
    """
    start = context.now - timedelta(seconds=params.duration_seconds)
    scope = (
        HealthSample.host_id == context.host.id,
        HealthSample.metric == params.metric,
        _same_subject(subject),
    )
    opening = await context.session.scalar(
        select(HealthSample.value)
        .where(*scope, HealthSample.sampled_at <= start)
        .order_by(HealthSample.sampled_at.desc(), HealthSample.id.desc())
        .limit(1)
    )
    if opening is None:
        return None
    inside = await context.session.scalars(
        select(HealthSample.value)
        .where(*scope, HealthSample.sampled_at > start, HealthSample.sampled_at <= context.now)
        .order_by(HealthSample.sampled_at)
    )
    values = [opening, *inside]
    compare = _COMPARISONS[params.comparison]
    if all(compare(value, params.value) for value in values):
        return values
    return None


@registry.register("threshold", ThresholdParams)
async def evaluate_threshold(context: RuleContext) -> Evaluation:
    params = ThresholdParams.model_validate(context.rule.params)
    violations = {}
    for subject in await _subjects(context, params):
        values = await _held_throughout(context, params, subject)
        if values is not None:
            violations[subject or ""] = values[-1]
    if not violations:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True,
        details={
            "metric": params.metric,
            "comparison": params.comparison,
            "threshold": params.value,
            "duration_seconds": params.duration_seconds,
            "latest": violations,
        },
    )
