"""Risk classes and executors are registry data; a new action type is one registration."""

from collections.abc import Mapping
from typing import Any

import pytest

from labhq.approvals import (
    ActionType,
    Executor,
    Registry,
    UnknownEntryError,
    default_actions,
    default_executors,
)
from labhq.db.enums import ApprovalStatus, RiskClass
from tests.approvals.conftest import World


@pytest.mark.parametrize("key", ["push", "merge", "delete_branch", "create_team"])
def test_phase_1_registers_the_heavy_actions(key: str) -> None:
    assert default_actions.get(key).risk_class == RiskClass.HEAVY


def test_phase_1_executes_push() -> None:
    assert "push" in default_executors


@pytest.mark.parametrize("risk_class", list(RiskClass))
async def test_the_risk_class_comes_from_the_registry(world: World, risk_class: RiskClass) -> None:
    world.actions.register("probe", ActionType("probe", risk_class))

    approval = await world.service.request("probe", {})

    assert approval.risk_class == risk_class


async def test_changing_a_registration_changes_the_risk_class(world: World) -> None:
    world.actions.register("merge", ActionType("merge", RiskClass.LIGHT), replace=True)

    approval = await world.service.request("merge", {"branch": "labhq/task-1"})

    assert approval.risk_class == RiskClass.LIGHT


async def test_a_new_action_type_needs_no_dispatcher_edit(world: World) -> None:
    executed: list[dict[str, Any]] = []

    def archive(payload: Mapping[str, Any]) -> dict[str, Any]:
        executed.append(dict(payload))
        return {"archived": payload["project"]}

    world.actions.register("archive_project", ActionType("archive_project", RiskClass.HEAVY))
    world.executors.register("archive_project", Executor(run=archive))

    requested = await world.service.request("archive_project", {"project": "demo"})
    assert executed == []
    approved = await world.service.approve(requested.id, decider="operator", confirmation="cli")

    assert requested.risk_class == RiskClass.HEAVY
    assert executed == [{"project": "demo"}]
    assert approved.status == ApprovalStatus.EXECUTED
    assert approved.execution == {"archived": "demo"}


async def test_an_executor_validates_the_payload_at_request_time(world: World) -> None:
    def reject_all(payload: Mapping[str, Any]) -> None:
        raise ValueError("bad payload")

    world.actions.register("checked", ActionType("checked", RiskClass.LIGHT))
    world.executors.register("checked", Executor(run=dict, validate=reject_all))

    with pytest.raises(ValueError, match="bad payload"):
        await world.service.request("checked", {})

    assert await world.service.list() == []


async def test_an_approved_action_without_an_executor_stays_approved(world: World) -> None:
    requested = await world.service.request("create_team", {"members": ["dev", "qa"]})

    approved = await world.service.approve(requested.id, decider="operator", confirmation="cli")

    assert approved.status == ApprovalStatus.APPROVED
    assert approved.executed_at is None


async def test_an_unknown_action_type_is_refused(world: World) -> None:
    with pytest.raises(UnknownEntryError, match="teleport"):
        await world.service.request("teleport", {})

    assert await world.service.list() == []


def test_a_registration_is_never_replaced_silently() -> None:
    registry = Registry[ActionType]("action type")
    registry.register("push", ActionType("push", RiskClass.HEAVY))

    with pytest.raises(ValueError, match="already registered"):
        registry.register("push", ActionType("push", RiskClass.LIGHT))

    assert registry.get("push").risk_class == RiskClass.HEAVY
    assert list(registry) == ["push"]


def test_a_copy_does_not_share_registrations() -> None:
    clone = default_actions.copy()
    clone.register("only_in_clone", ActionType("only_in_clone", RiskClass.LIGHT))

    assert "only_in_clone" not in default_actions
