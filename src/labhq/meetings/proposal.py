"""The CEO proposals an owner can pin to the Call Center and discuss: `kind -> description`.

A proposal is a CEO report or an approval waiting for the owner. Its text is read here for
the CEO's context and for a decision room's prompts; a new kind of proposal is one `register`.
"""

import json
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals.registry import Registry
from labhq.db.models import Approval, CeoReport

MAX_CHARS = 2000

# `(db, id) -> (project_id, text)`; None when there is no such proposal.
type Describe = Callable[[AsyncSession, int], Awaitable["Proposal | None"]]


class Proposal:
    def __init__(self, kind: str, id: int, project_id: int | None, text: str) -> None:
        self.kind = kind
        self.id = id
        self.project_id = project_id
        self.text = text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


async def _report(db: AsyncSession, report_id: int) -> Proposal | None:
    report = await db.get(CeoReport, report_id)
    if report is None:
        return None
    refs = f"\n({', '.join(report.refs)})" if report.refs else ""
    return Proposal("report", report.id, None, report.text + refs)


async def _approval(db: AsyncSession, approval_id: int) -> Proposal | None:
    approval = await db.get(Approval, approval_id)
    if approval is None:
        return None
    payload = json.dumps(approval.payload, ensure_ascii=False, sort_keys=True)
    project = approval.payload.get("project_id")
    text = f"{approval.type} ({approval.risk_class}): {payload}"
    return Proposal("approval", approval.id, project if isinstance(project, int) else None, text)


default_proposals = Registry[Describe]("proposal kind")
default_proposals.register("report", _report)
default_proposals.register("approval", _approval)
