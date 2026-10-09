"""Without an explicit kind a role runs on its default adapter; an explicit kind wins (#190)."""

import pytest

from labhq.adapters import UnknownAdapterError
from labhq.hierarchy import HierarchySettings
from tests.hierarchy.conftest import World

HEADLESS = {"worker": "claude", "it": "claude"}


def test_workers_and_it_default_to_headless_and_leaders_keep_the_org_adapter() -> None:
    settings = HierarchySettings(org_adapter="tmux")

    assert settings.role_adapters == HEADLESS
    assert settings.adapter_for("worker") == "claude"
    assert settings.adapter_for("it") == "claude"
    for role in ("manager", "head", "lead", "ceo"):
        assert settings.adapter_for(role) == "tmux"


def test_an_explicit_kind_overrides_the_role_default() -> None:
    assert HierarchySettings().adapter_for("worker", "tmux") == "tmux"


def test_the_role_table_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LABHQ_ROLE_ADAPTERS", '{"worker": "ollama", "lead": "claude"}')

    settings = HierarchySettings()

    assert settings.adapter_for("worker") == "ollama"
    assert settings.adapter_for("lead") == "claude"


async def test_a_worker_created_without_a_kind_gets_the_role_default(world: World) -> None:
    world.settings.role_adapters = {"worker": "fake"}
    manager = await world.active_manager()
    lead = await world.hierarchy.create_agent(manager.id, role="lead", title="Lead")
    worker = await world.hierarchy.create_agent(
        manager.id, role="worker", title="Dev", reports_to=lead.id
    )

    assert (manager.adapter, lead.adapter, worker.adapter) == ("fake", "fake", "fake")


async def test_the_default_must_be_a_registered_adapter(world: World) -> None:
    world.settings.role_adapters = dict(HEADLESS)
    manager = await world.active_manager()
    lead = await world.hierarchy.create_agent(manager.id, role="lead", title="Lead")

    # The table names `claude`, which this world does not register.
    with pytest.raises(UnknownAdapterError, match="claude"):
        await world.hierarchy.create_agent(
            manager.id, role="worker", title="Dev", reports_to=lead.id
        )


async def test_a_team_member_without_an_adapter_gets_its_role_default(world: World) -> None:
    world.settings.role_adapters = {"worker": "fake"}
    manager = await world.active_manager()
    ids = await world.hierarchy.staff_team(
        manager.id,
        [
            {"key": "lead", "role": "lead", "title": "Lead"},
            {"key": "dev", "role": "worker", "title": "Dev", "reports_to": "lead"},
            {
                "key": "other",
                "role": "worker",
                "title": "Other",
                "reports_to": "lead",
                "adapter": "fake",
            },
        ],
    )

    assert {(await world.agent(i)).adapter for i in ids.values()} == {"fake"}


async def test_a_manager_assigned_without_an_adapter_keeps_the_org_adapter(world: World) -> None:
    assert (await world.active_manager()).adapter == "fake"
