"""Who reports to whom (plan §2). The reporting lines are a table, not code paths."""

from collections.abc import Mapping
from dataclasses import dataclass

from labhq.work import WorkError


class HierarchyError(WorkError):
    """A hierarchy request that cannot be carried out as given; the message says why."""


class ReportingLineError(HierarchyError, ValueError):
    pass


CEO = "ceo"
MANAGER = "manager"
LEAD = "lead"
WORKER = "worker"
IT = "it"
HEAD = "head"


@dataclass(frozen=True)
class Role:
    key: str
    # The roles this role may report to; empty only at the top.
    reports_to: frozenset[str]


def _role(key: str, *reports_to: str) -> Role:
    return Role(key, frozenset(reports_to))


ROLES: Mapping[str, Role] = {
    role.key: role
    for role in (
        _role(CEO),
        _role(MANAGER, CEO),
        _role(LEAD, MANAGER),
        # A project worker reports to a lead; a department worker reports to its head.
        _role(WORKER, LEAD, HEAD),
        _role(IT, CEO),
        _role(HEAD, CEO),
    )
}


def role(key: str) -> Role:
    try:
        return ROLES[key]
    except KeyError:
        raise ReportingLineError(f"unknown role {key!r}; known: {', '.join(ROLES)}") from None


def check_reports_to(child: str, parent: str | None) -> None:
    """Refuse any reporting line the table does not list."""
    allowed = role(child).reports_to
    if (parent is None and not allowed) or parent in allowed:
        return
    above = " or ".join(f"a {key}" for key in sorted(allowed)) or "no one"
    given = "no one" if parent is None else f"a {parent}"
    raise ReportingLineError(f"a {child} reports to {above}, not to {given}")
