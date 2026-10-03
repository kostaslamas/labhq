"""Every table. Importing this package registers them all on `Base.metadata`."""

from labhq.db.models.approvals import Approval
from labhq.db.models.budgets import BudgetWarning
from labhq.db.models.callcenter import (
    AgentQuestion,
    Call,
    CallRequest,
    Delivery,
    Notification,
    StatusUpdate,
)
from labhq.db.models.chat import ChatBinding
from labhq.db.models.health import HealthRule, HealthSample, Host, Incident
from labhq.db.models.runs import AgentTaskSession, CostEvent, Run, RunEvent, WakeupRequest
from labhq.db.models.usage import UsageReading
from labhq.db.models.work import Agent, Comment, Project, Task

__all__ = [
    "Agent",
    "AgentQuestion",
    "AgentTaskSession",
    "Approval",
    "BudgetWarning",
    "Call",
    "CallRequest",
    "ChatBinding",
    "Comment",
    "CostEvent",
    "Delivery",
    "HealthRule",
    "HealthSample",
    "Host",
    "Incident",
    "Notification",
    "Project",
    "Run",
    "RunEvent",
    "StatusUpdate",
    "Task",
    "UsageReading",
    "WakeupRequest",
]
