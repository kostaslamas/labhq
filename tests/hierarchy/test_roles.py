"""Who reports to whom is a table; any line outside it is refused."""

import pytest
from pydantic import ValidationError

from labhq.hierarchy import ROLES, ReportingLineError, TeamProposal, check_reports_to

ALLOWED = [("worker", "lead"), ("lead", "manager"), ("manager", "ceo"), ("it", "ceo")]


@pytest.mark.parametrize(("child", "parent"), ALLOWED)
def test_the_table_allows_its_reporting_lines(child: str, parent: str) -> None:
    check_reports_to(child, parent)


def test_the_ceo_reports_to_no_one() -> None:
    check_reports_to("ceo", None)


REFUSED = [
    (child, parent)
    for child in ROLES
    for parent in [*ROLES, None]
    if (child, parent) not in {*ALLOWED, ("ceo", None)}
]


@pytest.mark.parametrize(("child", "parent"), REFUSED)
def test_every_other_reporting_line_is_refused(child: str, parent: str | None) -> None:
    with pytest.raises(ReportingLineError):
        check_reports_to(child, parent)


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ReportingLineError, match="unknown role"):
        check_reports_to("intern", "lead")


@pytest.mark.parametrize(
    "members",
    [
        # A worker straight under the manager skips the lead.
        [{"key": "w", "role": "worker", "title": "W", "adapter": "fake"}],
        # A lead under another lead.
        [
            {"key": "a", "role": "lead", "title": "A", "adapter": "fake"},
            {"key": "b", "role": "lead", "title": "B", "adapter": "fake", "reports_to": "a"},
        ],
        # A manager cannot propose another manager.
        [{"key": "m", "role": "manager", "title": "M", "adapter": "fake"}],
    ],
)
def test_a_proposal_with_a_line_outside_the_table_is_refused(members: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError, match="reports to"):
        TeamProposal.model_validate({"manager_id": 1, "members": members})


def test_a_proposal_naming_a_missing_member_is_refused() -> None:
    members = [{"key": "w", "role": "worker", "title": "W", "adapter": "fake", "reports_to": "x"}]
    with pytest.raises(ValidationError, match="not proposed"):
        TeamProposal.model_validate({"manager_id": 1, "members": members})


def test_creation_order_puts_every_lead_before_its_workers() -> None:
    proposal = TeamProposal.model_validate(
        {
            "manager_id": 1,
            "members": [
                {"key": "w", "role": "worker", "title": "W", "adapter": "fake", "reports_to": "l"},
                {"key": "l", "role": "lead", "title": "L", "adapter": "fake"},
            ],
        }
    )
    assert [member.key for member in proposal.in_creation_order()] == ["l", "w"]
