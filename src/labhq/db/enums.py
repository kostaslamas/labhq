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
    OWNER_MESSAGE = "owner_message"


class WakeupStatus(StrEnum):
    PENDING = "pending"
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


class CallStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class CallRequestStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    FAILED = "failed"
    EXPIRED = "expired"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class MeetingStatus(StrEnum):
    # Waiting for the light `start_meeting` approval.
    REQUESTED = "requested"
    RUNNING = "running"
    # Over, with or without minutes: a budget stop ends a meeting here too.
    ENDED = "ended"
    # The minutes could not be produced or recorded; the transcript stays.
    FAILED = "failed"
    # The approval was rejected or cancelled before the meeting started.
    CANCELLED = "cancelled"


class TranscriptSource(StrEnum):
    AGENT = "agent"
    OWNER = "owner"
    SYSTEM = "system"
