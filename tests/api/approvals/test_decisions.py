"""Deciding approvals over HTTP: a tap for light, a passkey for heavy, never twice."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from labhq.approvals import ApprovalService
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval
from labhq.worktrees import Worktree
from labhq.worktrees.git import run_git
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE


def decide(
    client: TestClient,
    approval: Approval,
    decision: str = "approve",
    *,
    key: str = "k1",
    credential: dict[str, Any] | None = None,
) -> Any:
    return client.post(
        f"/api/approvals/{approval.id}/decision",
        json={"decision": decision, "credential": credential},
        headers={**WRITE, "Idempotency-Key": key},
    )


def assertion_for(client: TestClient, authenticator: SoftwareAuthenticator, purpose_id: int) -> Any:
    response = client.post(f"/api/approvals/{purpose_id}/step-up", headers=WRITE)
    assert response.status_code == 200, response.text
    return authenticator.get(response.json(), LOCAL)


def remote_refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname)", cwd=remote)


async def status_of(service: ApprovalService, approval: Approval) -> ApprovalStatus:
    return (await service.get(approval.id)).status


async def test_a_light_approval_resolves_with_one_tap(
    signed_in: TestClient, service: ApprovalService, light: Approval
) -> None:
    response = decide(signed_in, light)

    assert response.status_code == 200, response.text
    stored = await service.get(light.id)
    assert stored.status == ApprovalStatus.APPROVED
    assert stored.confirmation_kind == "tap"
    assert stored.decided_by == "web:owner"
    assert stored.decided_at is not None
    assert response.json()["confirmation_kind"] == "tap"


async def test_a_light_approval_can_be_rejected(
    signed_in: TestClient, service: ApprovalService, light: Approval
) -> None:
    assert decide(signed_in, light, "reject").status_code == 200
    stored = await service.get(light.id)
    assert (stored.status, stored.confirmation_kind) == (ApprovalStatus.REJECTED, "tap")


async def test_the_decision_needs_a_session(
    app_client: TestClient, service: ApprovalService, light: Approval
) -> None:
    assert decide(app_client, light).status_code == 401
    assert await status_of(service, light) == ApprovalStatus.PENDING


async def test_a_heavy_approval_without_an_assertion_stays_pending(
    signed_in: TestClient, service: ApprovalService, heavy: Approval, remote: Path
) -> None:
    before = remote_refs(remote)

    response = decide(signed_in, heavy)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "step_up_required"
    assert await status_of(service, heavy) == ApprovalStatus.PENDING
    assert remote_refs(remote) == before


async def test_a_failed_assertion_leaves_a_heavy_approval_pending(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    service: ApprovalService,
    heavy: Approval,
    remote: Path,
) -> None:
    before = remote_refs(remote)
    assertion = assertion_for(signed_in, enrolled, heavy.id)
    assertion["response"]["signature"] = assertion["response"]["signature"][::-1]

    response = decide(signed_in, heavy, credential=assertion)

    assert response.status_code == 403
    assert await status_of(service, heavy) == ApprovalStatus.PENDING
    assert remote_refs(remote) == before


async def test_an_assertion_for_another_approval_does_not_pass(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    service: ApprovalService,
    heavy: Approval,
    light: Approval,
    remote: Path,
) -> None:
    before = remote_refs(remote)
    other = assertion_for(signed_in, enrolled, light.id)

    response = decide(signed_in, heavy, credential=other)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "challenge_invalid"
    assert await status_of(service, heavy) == ApprovalStatus.PENDING
    assert remote_refs(remote) == before


async def test_a_heavy_push_approved_with_a_passkey_is_pushed(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    service: ApprovalService,
    heavy: Approval,
    remote: Path,
    worktree: Worktree,
) -> None:
    assertion = assertion_for(signed_in, enrolled, heavy.id)

    response = decide(signed_in, heavy, credential=assertion)

    assert response.status_code == 200, response.text
    stored = await service.get(heavy.id)
    assert stored.status == ApprovalStatus.EXECUTED
    assert (stored.confirmation_kind, stored.decided_by) == ("passkey", "web:owner")
    assert worktree.branch in remote_refs(remote)


async def test_a_used_assertion_cannot_be_replayed_on_another_approval_or_again(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    service: ApprovalService,
    heavy: Approval,
    ids: dict[str, int],
) -> None:
    assertion = assertion_for(signed_in, enrolled, heavy.id)
    assert decide(signed_in, heavy, credential=assertion).status_code == 200
    second = await service.request(
        "delete_branch",
        {"branch": "x"},
        task_id=ids["task"],
    )

    replay = decide(signed_in, second, key="k2", credential=assertion)

    assert replay.status_code == 403
    assert await status_of(service, second) == ApprovalStatus.PENDING


async def test_a_repeated_key_does_not_decide_twice(
    signed_in: TestClient, service: ApprovalService, light: Approval
) -> None:
    first = decide(signed_in, light, key="same")
    stored = await service.get(light.id)

    again = decide(signed_in, light, key="same")

    assert again.status_code == 200
    assert again.json() == first.json()
    assert (await service.get(light.id)).decided_at == stored.decided_at


async def test_another_key_after_the_decision_is_a_conflict(
    signed_in: TestClient, light: Approval
) -> None:
    assert decide(signed_in, light, key="a").status_code == 200
    again = decide(signed_in, light, "reject", key="b")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "approval_not_pending"


async def test_an_approval_decided_elsewhere_offers_no_step_up(
    signed_in: TestClient, service: ApprovalService, heavy: Approval
) -> None:
    await service.reject(heavy.id, decider="gate", confirmation="cli")
    response = signed_in.post(f"/api/approvals/{heavy.id}/step-up", headers=WRITE)
    assert response.status_code == 409


async def test_a_heavy_reject_needs_only_the_session(
    signed_in: TestClient, service: ApprovalService, heavy: Approval
) -> None:
    assert decide(signed_in, heavy, "reject").status_code == 200
    assert await status_of(service, heavy) == ApprovalStatus.REJECTED


async def test_the_idempotency_key_is_required(signed_in: TestClient, light: Approval) -> None:
    response = signed_in.post(
        f"/api/approvals/{light.id}/decision", json={"decision": "approve"}, headers=WRITE
    )
    assert response.status_code == 422
