"""The IT department's agent and what wakes it (plan §2.2). Its tools live in `labhq.roles`."""

from labhq.it.agent import IT_CONFIG, ensure_it_agent, find_it_agent
from labhq.it.department import ItDepartment, ItPass, it_step
from labhq.it.settings import ItSettings
from labhq.it.wakeups import (
    REPORT_REASON,
    incident_key,
    report_key,
    wake_for_incidents,
    wake_for_report,
)

__all__ = [
    "IT_CONFIG",
    "REPORT_REASON",
    "ItDepartment",
    "ItPass",
    "ItSettings",
    "ensure_it_agent",
    "find_it_agent",
    "incident_key",
    "it_step",
    "report_key",
    "wake_for_incidents",
    "wake_for_report",
]
