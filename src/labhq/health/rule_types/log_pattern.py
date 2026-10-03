"""`log_pattern`: journal errors, or matches of a pattern, above a count in a window.

Without a pattern it reads `journal.errors`, the error count since the previous sample. With
one it reads `journal.matches` whose subject is the pattern, so a collector that counts a
pattern's matches records them under the pattern itself.
"""

from pydantic import BaseModel, ConfigDict, Field

from labhq.health.rule_types.samples import NO_SUBJECT, subjects, window
from labhq.health.rules import Evaluation, RuleContext, registry

ERRORS_METRIC = "journal.errors"
MATCHES_METRIC = "journal.matches"


class LogPatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str | None = Field(default=None, min_length=1)
    # Violated when the sum over the window is above this.
    count: int = Field(ge=0)
    window_seconds: float = Field(default=3600.0, gt=0)


@registry.register("log_pattern", LogPatternParams)
async def evaluate_log_pattern(context: RuleContext) -> Evaluation:
    params = LogPatternParams.model_validate(context.rule.params)
    metric = MATCHES_METRIC if params.pattern is not None else ERRORS_METRIC
    totals = {}
    for subject in await subjects(context, metric, params.pattern):
        points = await window(context, metric, subject, params.window_seconds)
        total = sum(value for _, value in points)
        if total > params.count:
            totals[subject or NO_SUBJECT] = total
    if not totals:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True,
        details={
            "metric": metric,
            "pattern": params.pattern,
            "count": params.count,
            "window_seconds": params.window_seconds,
            "totals": totals,
        },
    )
