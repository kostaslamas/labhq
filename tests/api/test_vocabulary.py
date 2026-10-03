import json
from enum import StrEnum

from starlette.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.openapi import render, schema
from labhq.api.settings import ApiSettings
from labhq.api.vocabulary import snake_case, status_enums
from labhq.db import enums

from ..conftest import REPO_ROOT
from .conftest import OWNER_HEADER

COMMITTED_SCHEMA = REPO_ROOT / "web" / "openapi.json"


def declared_status_enums() -> set[str]:
    return {
        name
        for name, value in vars(enums).items()
        if isinstance(value, type) and issubclass(value, StrEnum) and name.endswith("Status")
    }


def test_every_status_enum_of_the_module_is_published() -> None:
    published = {enum.__name__ for enum in status_enums().values()}
    assert published == declared_status_enums()
    assert {"RunStatus", "ApprovalStatus", "TaskStatus"} <= published
    assert "run_status" in status_enums()


def test_snake_case_names_each_field_after_its_enum() -> None:
    assert snake_case("CallRequestStatus") == "call_request_status"
    assert snake_case("RunStatus") == "run_status"


def test_the_route_returns_every_value_in_declaration_order(
    resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    with TestClient(create_app(settings=api_settings, resolvers=resolvers)) as client:
        response = client.get("/api/vocabulary", headers={OWNER_HEADER: "owner"})
    assert response.status_code == 200
    body = response.json()
    assert body == {key: [value.value for value in enum] for key, enum in status_enums().items()}
    assert body["run_status"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "interrupted",
        "timed_out",
    ]


def test_the_route_needs_the_owner(resolvers: ResolverRegistry, api_settings: ApiSettings) -> None:
    with TestClient(create_app(settings=api_settings, resolvers=resolvers)) as client:
        response = client.get("/api/vocabulary")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_the_openapi_schema_carries_each_enum_and_its_values() -> None:
    components = schema()["components"]["schemas"]
    fields = components["Vocabulary"]["properties"]
    assert set(fields) == set(status_enums())
    assert set(components["Vocabulary"]["required"]) == set(status_enums())
    for key, enum in status_enums().items():
        assert fields[key]["items"]["$ref"] == f"#/components/schemas/{enum.__name__}"
        assert components[enum.__name__]["enum"] == [value.value for value in enum]


def test_the_committed_schema_matches_the_api() -> None:
    # The same check as the drift step in web.yml, earlier and with a clearer message.
    committed = json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
    assert committed == json.loads(render()), "run `npm run api:generate` in web/"
