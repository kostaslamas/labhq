"""Listing and reading approvals: pending first, what would run, who decided."""

from fastapi.testclient import TestClient
from sqlalchemy import update

from labhq.approvals import ApprovalService
from labhq.cli.context import Context
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval
from labhq.worktrees import Worktree


async def test_the_list_puts_pending_first_and_pages_by_cursor(
    signed_in: TestClient, service: ApprovalService, light: Approval
) -> None:
    await service.reject(light.id, decider="cli:a", confirmation="cli")
    newer = [await service.request("assign_task", {"n": n}) for n in range(3)]

    seen: list[int] = []
    cursor: str | None = None
    while True:
        response = signed_in.get("/api/approvals", params={"cursor": cursor} if cursor else {})
        assert response.status_code == 200, response.text
        seen += [item["id"] for item in response.json()["items"]]
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break

    assert seen == [approval.id for approval in reversed(newer)] + [light.id]


async def test_the_status_filter_narrows_the_list(
    signed_in: TestClient, service: ApprovalService, light: Approval
) -> None:
    await service.reject(light.id, decider="cli:a", confirmation="cli")
    await service.request("assign_task", {})

    items = signed_in.get("/api/approvals", params={"status": "rejected"}).json()["items"]

    assert [item["id"] for item in items] == [light.id]


async def test_the_detail_says_what_will_run(
    signed_in: TestClient, heavy: Approval, ids: dict[str, int], worktree: Worktree
) -> None:
    body = signed_in.get(f"/api/approvals/{heavy.id}").json()

    assert body["type"] == "push"
    assert body["risk_class"] == "heavy"
    assert body["status"] == "pending"
    assert body["branch"] == worktree.branch
    assert body["remote"] == heavy.payload["url"]
    assert body["project"]["id"] == ids["project"]
    assert body["task"]["id"] == ids["task"]
    assert body["requester"]["id"] == ids["agent"]
    assert body["decided_by"] is None


async def test_a_gate_decision_shows_its_decider_and_kind(
    signed_in: TestClient, context: Context, light: Approval
) -> None:
    # What an external gate would have stored; the UI shows it as written.
    async with context.sessions() as db:
        await db.execute(
            update(Approval)
            .where(Approval.id == light.id)
            .values(
                status=ApprovalStatus.APPROVED,
                decided_by="gate:ci",
                confirmation_kind="external_gate",
                decided_at=context.clock.now(),
            )
        )
        await db.commit()

    body = signed_in.get(f"/api/approvals/{light.id}").json()

    assert (body["decided_by"], body["confirmation_kind"]) == ("gate:ci", "external_gate")


async def test_an_unknown_approval_is_404(signed_in: TestClient) -> None:
    response = signed_in.get("/api/approvals/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "approval_not_found"
