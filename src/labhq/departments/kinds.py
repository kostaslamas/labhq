"""Department kinds as a registry: `kind -> {instructions, skills, deliverables, tools}`.

A new kind is a registration, like an adapter kind or a rule type. A kind either owns a role
for its head (IT's agent is an `it`, whose instruction is registered under that role) or uses
the generic `head` role, and then its instructions reach every member through the agent's
`config["department"]` (`labhq.departments.prompts`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from labhq.approvals.registry import Registry
from labhq.hierarchy import HEAD
from labhq.work.deliverables import DECISION, DOCUMENT, REPORT


@dataclass(frozen=True)
class DepartmentKind:
    key: str
    instructions: str
    skills: tuple[str, ...] = ()
    deliverables: frozenset[str] = frozenset({DOCUMENT, REPORT, DECISION})
    # Tool names written to the head's and the members' `config["tools"]`.
    default_tools: frozenset[str] = frozenset()
    head_role: str = HEAD
    # Laid under the head's `agents.config`, for example IT's read-only mode.
    head_config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def tags_agents(self) -> bool:
        """True when agents carry the department in their config; a kind with its own role
        has its instruction registered under that role instead."""
        return self.head_role == HEAD


default_kinds = Registry[DepartmentKind]("department kind")
