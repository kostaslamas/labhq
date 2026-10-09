import pytest

import labhq.mcp.tools  # noqa: F401  (registers every tool)
from labhq.mcp.tools.registry import ToolSpec, default_registry

# Plan 3.3: reads are read-only, `decide` is the one destructive tool, other writes are not.
EXPECTED: dict[str, tuple[bool, bool | None]] = {
    "brief": (True, None),
    "inbox": (True, None),
    "health": (True, None),
    "reports": (True, None),
    "decide": (False, True),
    "order": (False, False),
    "answer": (False, False),
    "ask_ceo": (False, False),
    "get_reply": (True, None),
    "meeting_minutes": (True, None),
    # `sessions` files the scan as CEO reports; `analyse` only records an approval.
    "sessions": (False, False),
    "analyse": (False, False),
}


def _specs() -> dict[str, ToolSpec]:
    return {spec.name: spec for spec in default_registry}


def test_the_registry_holds_exactly_the_call_center_tools() -> None:
    assert set(_specs()) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_tool_has_the_annotation_the_plan_gives_it(name: str) -> None:
    annotations = _specs()[name].annotations
    assert annotations is not None, f"{name} has no annotations"
    read_only, destructive = EXPECTED[name]
    assert annotations.read_only_hint is read_only
    assert annotations.destructive_hint is destructive


def test_descriptions_state_the_rules() -> None:
    specs = _specs()
    assert "passkey" in specs["decide"].description
    assert "short" in specs["answer"].description
    assert "A12" in specs["decide"].description
    assert "Q7" in specs["answer"].description
    assert "CEO" in specs["order"].description
    assert "never reworded" in specs["order"].description
    assert "passkey" in specs["order"].description
    assert "wakes nobody" in specs["reports"].description
    assert "get_reply" in specs["ask_ceo"].description
    assert "same ticket" in specs["get_reply"].description
    assert "never ask again" in specs["get_reply"].description
    assert "wait_seconds" in specs["ask_ceo"].description
    assert "asks which one" in specs["meeting_minutes"].description
    assert "no model is called" in specs["sessions"].description
    assert "ONE project" in specs["analyse"].description
    assert "starts nothing" in specs["analyse"].description
