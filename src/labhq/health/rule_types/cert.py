"""`cert_expiry`: a certificate expires within N days.

Reads `cert.days_left` (subject: `host:port` or a file path).
"""

from pydantic import BaseModel, ConfigDict, Field

from labhq.health.rule_types.samples import latest
from labhq.health.rules import Evaluation, RuleContext, registry

METRIC = "cert.days_left"


class CertExpiryParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    days: float = Field(gt=0)
    # One certificate; None watches every certificate the host reports.
    subject: str | None = Field(default=None, min_length=1)


@registry.register("cert_expiry", CertExpiryParams)
async def evaluate_cert_expiry(context: RuleContext) -> Evaluation:
    params = CertExpiryParams.model_validate(context.rule.params)
    seen = await latest(context, METRIC, params.subject)
    expiring = {subject: days for subject, days in seen.items() if days <= params.days}
    if not expiring:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True, details={"metric": METRIC, "days": params.days, "latest": expiring}
    )
