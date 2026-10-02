"""Status vocabularies: one `StrEnum` per concept, shared by models, engine and CLI."""

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AgentStatus(StrEnum):
    # New agents need approval by default (plan §5, rule 4).
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class WakeupSource(StrEnum):
    TIMER = "timer"
    ASSIGNMENT = "assignment"
    COMMENT = "comment"
    APPROVAL_RESOLVED = "approval_resolved"
    MEETING = "meeting"


class WakeupStatus(StrEnum):
    PENDING = "pending"
    # Merged into another pending request; the row keeps its key so a retry stays a no-op.
    COALESCED = "coalesced"
    DISPATCHED = "dispatched"
    REFUSED = "refused"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # An interrupt ends a run here, never in FAILED (spikes/agent_sdk/RESULTS.md).
    INTERRUPTED = "interrupted"
    TIMED_OUT = "timed_out"


class RiskClass(StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"


class HostStatus(StrEnum):
    UNKNOWN = "unknown"
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthRuleAction(StrEnum):
    NOTIFY = "notify"
    TICKET = "ticket"


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class BudgetScope(StrEnum):
    AGENT = "agent"
    PROJECT = "project"
