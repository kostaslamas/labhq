"""One-line renderings of rows for the terminal. Amounts go through `labhq.money`."""

from labhq.db.models import Approval, CostEvent, HealthSample, Incident, Run
from labhq.money import format_micros


def run_line(run: Run) -> str:
    reason = (run.exit or {}).get("terminal_reason") or (run.exit or {}).get("error") or "-"
    return f"run {run.id}: {run.status} (agent {run.agent_id}, task {run.task_id}, {reason})"


def cost_line(cost: CostEvent) -> str:
    return (
        f"cost_events {cost.id}: run {cost.run_id}, agent {cost.agent_id}, "
        f"project {cost.project_id}, {format_micros(cost.cost_micros)} "
        f"({cost.cost_micros} micros), model {cost.model or '-'}, "
        f"tokens in {cost.input_tokens} out {cost.output_tokens}"
    )


def approval_line(approval: Approval) -> str:
    payload = approval.payload
    target = ""
    if "branch" in payload and "commit" in payload:
        target = f" {payload['branch']} @ {str(payload['commit'])[:12]} -> {payload.get('url')}"
    # An adoption carries the warnings its confirmation must show (ADR 0005).
    warnings = "".join(f"\n  warning: {warning}" for warning in payload.get("warnings", ()))
    return (
        f"approval {approval.id}: {approval.type} [{approval.risk_class}] {approval.status}"
        f" (task {approval.task_id}, agent {approval.requested_by_agent_id}){target}{warnings}"
    )


def execution_line(approval: Approval) -> str:
    return f"  execution: {approval.execution}" if approval.execution else ""


def sample_line(host: str, sample: HealthSample) -> str:
    subject = f" [{sample.subject}]" if sample.subject else ""
    return f"{host} {sample.metric}{subject} = {sample.value:g} at {sample.sampled_at.isoformat()}"


def incident_line(incident: Incident, rule_name: str, host: str) -> str:
    return (
        f"incident {incident.id}: {rule_name} on {host}, open since "
        f"{incident.opened_at.isoformat()} {incident.details}"
    )
