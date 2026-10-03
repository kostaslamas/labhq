"""The Phase 4 topics. A topic whose page shows a new kind of change adds an aggregate."""

from sqlalchemy import func

from labhq.db.enums import ApprovalStatus, IncidentStatus, QuestionStatus, RunStatus
from labhq.db.models import AgentQuestion, Approval, CostEvent, Incident, Run, Task
from labhq.live.registry import aggregates, default_topics, status_counts

default_topics.register(
    "approvals",
    aggregates(
        func.max(Approval.id),
        func.count(Approval.id),
        *status_counts(Approval.status, ApprovalStatus),
    ),
)
default_topics.register(
    "tasks",
    aggregates(func.max(Task.id), func.count(Task.id), func.max(Task.updated_at)),
)
# Not the heartbeat: it moves every few seconds while a run is live and changes nothing shown.
default_topics.register(
    "runs",
    aggregates(
        func.max(Run.id),
        func.count(Run.id),
        func.max(Run.finished_at),
        *status_counts(Run.status, RunStatus),
    ),
)
default_topics.register(
    "costs",
    aggregates(func.max(CostEvent.id), func.count(CostEvent.id)),
)
default_topics.register(
    "questions",
    aggregates(
        func.max(AgentQuestion.id),
        func.count(AgentQuestion.id),
        *status_counts(AgentQuestion.status, QuestionStatus),
    ),
)
default_topics.register(
    "incidents",
    aggregates(
        func.max(Incident.id),
        func.count(Incident.id),
        *status_counts(Incident.status, IncidentStatus),
    ),
)
