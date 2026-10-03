import logging
from typing import Annotated

import pytest
from fastapi import APIRouter, HTTPException, Query
from starlette.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import OwnerDep, ResolverRegistry
from labhq.api.errors import ApiError
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings

from .conftest import OWNER_HEADER

SIGNED_IN = {OWNER_HEADER: "kostas"}


def failing_router() -> APIRouter:
    router = APIRouter(prefix="/failures")

    @router.get("/boom")
    async def failures_boom(owner: OwnerDep) -> None:
        raise RuntimeError("database password is hunter2")

    @router.get("/missing")
    async def failures_missing(owner: OwnerDep) -> None:
        raise ApiError(404, "approval_not_found", "No approval has that id.")

    @router.get("/plain")
    async def failures_plain(owner: OwnerDep) -> None:
        raise HTTPException(409, "Already decided.")

    @router.get("/count")
    async def failures_count(owner: OwnerDep, n: Annotated[int, Query(ge=1)]) -> int:
        return n

    return router


@pytest.fixture
def client(resolvers: ResolverRegistry, api_settings: ApiSettings) -> TestClient:
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(failing_router())
    app = create_app(routers=routers, resolvers=resolvers, settings=api_settings)
    # Unhandled errors must become a 500 envelope, not a re-raise into the test.
    return TestClient(app, raise_server_exceptions=False)


def assert_envelope(body: object, code: str) -> str:
    assert isinstance(body, dict)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    message = body["error"]["message"]
    assert isinstance(message, str) and message
    return message


def test_unknown_route_is_a_404_envelope(client: TestClient) -> None:
    for path in ("/api/nowhere", "/nowhere"):
        response = client.get(path, headers=SIGNED_IN)
        assert response.status_code == 404
        assert_envelope(response.json(), "not_found")


def test_missing_session_is_a_401_envelope(client: TestClient) -> None:
    response = client.get("/api/failures/missing")
    assert response.status_code == 401
    assert_envelope(response.json(), "unauthorized")


def test_validation_is_a_422_envelope(client: TestClient) -> None:
    response = client.get("/api/failures/count", params={"n": "zero"}, headers=SIGNED_IN)
    assert response.status_code == 422
    message = assert_envelope(response.json(), "validation_error")
    assert "n" in message


def test_unhandled_error_is_a_500_envelope_with_details_only_in_the_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="labhq.api.errors"):
        response = client.get("/api/failures/boom", headers=SIGNED_IN)
    assert response.status_code == 500
    assert_envelope(response.json(), "internal_error")
    assert "hunter2" not in response.text
    assert "hunter2" in caplog.text


def test_route_errors_keep_their_code_and_message(client: TestClient) -> None:
    missing = client.get("/api/failures/missing", headers=SIGNED_IN)
    assert missing.status_code == 404
    assert assert_envelope(missing.json(), "approval_not_found") == "No approval has that id."
    plain = client.get("/api/failures/plain", headers=SIGNED_IN)
    assert plain.status_code == 409
    assert assert_envelope(plain.json(), "conflict") == "Already decided."


def test_wrong_method_is_a_405_envelope(client: TestClient) -> None:
    response = client.post("/api/health")
    assert response.status_code == 405
    assert_envelope(response.json(), "method_not_allowed")
