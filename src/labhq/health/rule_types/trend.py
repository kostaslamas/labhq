"""`trend`: a metric crosses a limit within a horizon, from a linear fit over a window.

"The disk is full in 5 days": least squares over the window's samples gives a slope and the
value now; the time to the limit is their distance over the slope. A series moving away from
the limit, a flat one and one already past it predict nothing; the last is the threshold
rule's business.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from labhq.health.rule_types.samples import NO_SUBJECT, subjects, window
from labhq.health.rules import Evaluation, RuleContext, registry

DAY_SECONDS = 86400.0


class TrendParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str = Field(min_length=1)
    limit: float
    within_days: float = Field(gt=0)
    window_seconds: float = Field(default=DAY_SECONDS, gt=0)
    # Fewer samples than this make no fit.
    min_samples: int = Field(default=3, ge=2)
    subject: str | None = Field(default=None, min_length=1)


def fit(points: list[tuple[datetime, float]], now: datetime) -> tuple[float, float] | None:
    """Slope per second and the fitted value at `now`, or None when time does not vary."""
    xs = [(at - now).total_seconds() for at, _ in points]
    ys = [value for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
    return slope, mean_y - slope * mean_x


def seconds_to_limit(slope: float, value_now: float, limit: float) -> float | None:
    if slope == 0:
        return None
    eta = (limit - value_now) / slope
    return eta if eta >= 0 else None


@registry.register("trend", TrendParams)
async def evaluate_trend(context: RuleContext) -> Evaluation:
    params = TrendParams.model_validate(context.rule.params)
    horizon = params.within_days * DAY_SECONDS
    forecasts = {}
    for subject in await subjects(context, params.metric, params.subject):
        points = await window(context, params.metric, subject, params.window_seconds)
        fitted = fit(points, context.now) if len(points) >= params.min_samples else None
        if fitted is None:
            continue
        slope, value_now = fitted
        eta = seconds_to_limit(slope, value_now, params.limit)
        if eta is not None and eta <= horizon:
            forecasts[subject or NO_SUBJECT] = {
                "days_to_limit": round(eta / DAY_SECONDS, 2),
                "latest": points[-1][1],
                "slope_per_day": round(slope * DAY_SECONDS, 4),
            }
    if not forecasts:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True,
        details={
            "metric": params.metric,
            "limit": params.limit,
            "within_days": params.within_days,
            "forecasts": forecasts,
        },
    )
