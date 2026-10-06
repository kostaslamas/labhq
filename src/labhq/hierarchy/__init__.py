"""The CEO, a manager per project and team proposals as heavy approvals (plan §2, §5).

Importing this package registers the `create_agent` and `create_team` executors with
`labhq.approvals`.
"""

from labhq.hierarchy.executors import (
    CREATE_AGENT,
    CREATE_TEAM,
    AgentApproval,
    EngineAccess,
    agent_executor,
    team_executor,
)
from labhq.hierarchy.roles import (
    CEO,
    HEAD,
    IT,
    LEAD,
    MANAGER,
    ROLES,
    WORKER,
    HierarchyError,
    ReportingLineError,
    Role,
    check_reports_to,
)
from labhq.hierarchy.service import Hierarchy, ManagerAssignment, Node, find_ceo
from labhq.hierarchy.settings import HierarchySettings
from labhq.hierarchy.team import (
    TEAM_SIZE_KEY,
    ProposedMember,
    TeamProposal,
    TeamSizeError,
    team_of,
    team_size_cap,
)

__all__ = [
    "CEO",
    "CREATE_AGENT",
    "CREATE_TEAM",
    "HEAD",
    "IT",
    "LEAD",
    "MANAGER",
    "ROLES",
    "TEAM_SIZE_KEY",
    "WORKER",
    "AgentApproval",
    "EngineAccess",
    "Hierarchy",
    "HierarchyError",
    "HierarchySettings",
    "ManagerAssignment",
    "Node",
    "ProposedMember",
    "ReportingLineError",
    "Role",
    "TeamProposal",
    "TeamSizeError",
    "agent_executor",
    "check_reports_to",
    "find_ceo",
    "team_executor",
    "team_of",
    "team_size_cap",
]
