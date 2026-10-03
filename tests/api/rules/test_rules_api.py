"""The rules API lists why each rule exists and lets the signed-in owner switch one off."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry
from labhq.api.rules.routes import router as rules_router
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.health.incidents import evaluate_rules
from tests.api.conftest import OWNER_HEADER
from tests.health.factories import add_host, add_rule, add_samples

CPU_OVER_90 = {"metric": "cpu.percent", "comparison": ">", "value": 90}
OWNER = {OWNER_HEADER: "the-owner"}


@pytest.fixture
def client(context: Context, resolvers: ResolverRegistry, tmp_path: Path) -> Iterator[TestClient]:
    routers = RouterRegistry()
    routers.register(rules_router)
    app = create_app(
        context, routers=routers, resolvers=resolvers, settings=ApiSettings(ui_dir=tmp_path / "ui")
    )
    with TestClient(app) as client:
        yield client


async def seed_violation(context: Context, clock: FakeClock) -> int:
    """A rule an agent added and a host that violates it; returns the rule id."""
    async with context.sessions() as db:
        host = await add_host(db, clock)
        rule = await add_rule(db, clock, params=CPU_OVER_90, host=host)
        rule.created_by = "agent:infra"
        rule.reason = "CPU pinned for an hour last week."
        await add_samples(db, host, "cpu.percent", [(clock.now(), 97.0)])
        await db.commit()
        return rule.id


async def evaluation_changes(context: Context, clock: FakeClock) -> int:
    async with context.sessions() as db:
        changes = await evaluate_rules(db, clock)
        await db.commit()
        return len(changes)


async def test_a_rule_is_listed_with_its_reason_creator_and_latest_result(
    client: TestClient, context: Context, clock: FakeClock
) -> None:
    rule_id = await seed_violation(context, clock)
    assert await evaluation_changes(context, clock) == 1

    response = client.get("/api/health/rules", headers=OWNER)

    assert response.status_code == 200
    [rule] = response.json()
    assert rule["id"] == rule_id
    assert rule["reason"] == "CPU pinned for an hour last week."
    assert rule["created_by"] == "agent:infra"
    assert (rule["type"], rule["action"], rule["host"], rule["enabled"]) == (
        "threshold",
        "notify",
        "box",
        True,
    )
    assert rule["params"] == CPU_OVER_90
    assert rule["latest"]["status"] == "open"
    assert rule["latest"]["details"]["latest"] == {"": 97.0}


async def test_a_rule_without_incidents_has_no_latest_result(
    client: TestClient, context: Context, clock: FakeClock
) -> None:
    await seed_violation(context, clock)

    [rule] = client.get("/api/health/rules", headers=OWNER).json()

    assert rule["latest"] is None


async def test_disabling_a_rule_stops_its_evaluation(
    client: TestClient, context: Context, clock: FakeClock
) -> None:
    rule_id = await seed_violation(context, clock)
    url = f"/api/health/rules/{rule_id}/enabled"

    response = client.post(url, json={"enabled": False}, headers=OWNER)

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert await evaluation_changes(context, clock) == 0

    client.post(url, json={"enabled": True}, headers=OWNER)
    assert await evaluation_changes(context, clock) == 1


async def test_disabling_records_the_owner_and_when(
    client: TestClient,
    context: Context,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rule_id = await seed_violation(context, clock)
    clock.advance(timedelta(minutes=5))

    with caplog.at_level(logging.INFO, logger="labhq.health.manage"):
        body = client.post(
            f"/api/health/rules/{rule_id}/enabled", json={"enabled": False}, headers=OWNER
        ).json()

    assert f"rule {rule_id} disabled by the-owner" in caplog.text
    assert body["updated_at"].startswith("2026-10-02T09:05:00")


def test_an_unknown_rule_is_a_404(client: TestClient) -> None:
    response = client.post("/api/health/rules/999/enabled", json={"enabled": False}, headers=OWNER)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "rule_not_found"


def test_without_a_session_both_routes_are_refused(client: TestClient) -> None:
    assert client.get("/api/health/rules").status_code == 401
    assert client.post("/api/health/rules/1/enabled", json={"enabled": False}).status_code == 401
