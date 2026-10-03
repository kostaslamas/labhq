"""`service_active`: a systemd unit or a container is not running.

Reads `service.active` or `container.running` (subject: the unit or container name, value 1
or 0). The latest sample decides.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labhq.health.rule_types.samples import latest
from labhq.health.rules import Evaluation, RuleContext, registry

METRICS: dict[str, str] = {"service": "service.active", "container": "container.running"}


class ServiceActiveParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["service", "container"] = "service"
    # The unit or container; None watches every one the host reports.
    name: str | None = Field(default=None, min_length=1)


@registry.register("service_active", ServiceActiveParams)
async def evaluate_service_active(context: RuleContext) -> Evaluation:
    params = ServiceActiveParams.model_validate(context.rule.params)
    metric = METRICS[params.kind]
    seen = await latest(context, metric, params.name)
    stopped = {name: value for name, value in seen.items() if value < 1}
    if not stopped:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True, details={"metric": metric, "kind": params.kind, "latest": stopped}
    )
