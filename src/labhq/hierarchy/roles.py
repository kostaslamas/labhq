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


@dataclass(frozen=True)
class Role:
    key: str
    # The one role this role reports to; None only at the top.
    reports_to: str | None


ROLES: Mapping[str, Role] = {
    role.key: role
    for role in (
        Role(CEO, None),
        Role(MANAGER, CEO),
        Role(LEAD, MANAGER),
        Role(WORKER, LEAD),
        Role(IT, CEO),
    )
}


def role(key: str) -> Role:
    try:
        return ROLES[key]
    except KeyError:
        raise ReportingLineError(f"unknown role {key!r}; known: {', '.join(ROLES)}") from None


def check_reports_to(child: str, parent: str | None) -> None:
    """Refuse any reporting line the table does not list."""
    expected = role(child).reports_to
    if parent != expected:
        above = "no one" if expected is None else f"a {expected}"
        given = "no one" if parent is None else f"a {parent}"
        raise ReportingLineError(f"a {child} reports to {above}, not to {given}")
