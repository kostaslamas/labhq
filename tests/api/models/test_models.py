"""The Models page over HTTP: readable with a session, saved only with a passkey, cost by model."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.models import router as models_router
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from labhq.db.models import CostEvent
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in
from tests.db.factories import project_agent_task

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]

WORKER = {"worker": {"model": "claude-opus-5-5", "effort": "high"}}


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(models_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


def assertion(client: TestClient, authenticator: SoftwareAuthenticator) -> Any:
    response = client.post(
        "/api/auth/step-up/options", json={"purpose": "models:policy"}, headers=WRITE
    )
    assert response.status_code == 200, response.text
    return authenticator.get(response.json(), LOCAL)


def test_the_table_and_the_known_models_are_listed(signed_in: TestClient) -> None:
    body = signed_in.get("/api/models").json()
    assert {m["id"] for m in body["models"]} >= {"claude-haiku-5-5", "claude-sonnet-5-5"}
    rows = {r["key"]: r for r in body["rows"]}
    assert rows["summary"]["model"] == "claude-haiku-5-5" and rows["summary"]["kind"] == "task"
    assert rows["ceo"]["effort"] == "high" and rows["ceo"]["kind"] == "role"


def test_saving_needs_a_passkey(signed_in: TestClient) -> None:
    response = signed_in.put("/api/models", json={"rows": WORKER}, headers=WRITE)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "step_up_required"
    rows = {r["key"]: r for r in signed_in.get("/api/models").json()["rows"]}
    assert rows["worker"]["model"] == "claude-sonnet-5-5"


def test_a_passkey_saves_the_row(signed_in: TestClient, enrolled: SoftwareAuthenticator) -> None:
    body = {"rows": WORKER, "credential": assertion(signed_in, enrolled)}
    response = signed_in.put("/api/models", json=body, headers=WRITE)
    assert response.status_code == 200, response.text
    rows = {r["key"]: r for r in signed_in.get("/api/models").json()["rows"]}
    assert (rows["worker"]["model"], rows["worker"]["effort"]) == ("claude-opus-5-5", "high")


def test_an_unknown_model_is_a_422_and_nothing_changes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    rows = {"worker": {"model": "claude-opus-5-5-20260101", "effort": "high"}}
    body = {"rows": rows, "credential": assertion(signed_in, enrolled)}
    response = signed_in.put("/api/models", json=body, headers=WRITE)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "model_policy_invalid"
    stored = {r["key"]: r for r in signed_in.get("/api/models").json()["rows"]}
    assert stored["worker"]["model"] == "claude-sonnet-5-5"


async def test_usage_reports_cost_by_model_in_micros(
    signed_in: TestClient, context: Context
) -> None:
    async with context.sessions() as db:
        _, agent, _ = await project_agent_task(db, context.clock)
        db.add(
            CostEvent(
                agent_id=agent.id,
                cost_micros=1_500,
                model="claude-haiku-5-5",
                input_tokens=1_000_000,
                output_tokens=0,
                created_at=context.clock.now(),
            )
        )
        await db.commit()
    (row,) = signed_in.get("/api/models/usage").json()
    assert row["model"] == "claude-haiku-5-5" and row["cost_micros"] == 1_500
    assert row["saved_micros"] == 2_000_000 - 1_500
