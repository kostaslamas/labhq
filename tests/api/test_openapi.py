import json
import re
import subprocess
import sys
from typing import Annotated, Any

from fastapi import APIRouter, Query

from labhq.api.app import create_app
from labhq.api.deps import OwnerDep
from labhq.api.openapi import render
from labhq.api.routes import RouterRegistry, default_routers, health_router

OPERATION_ID = re.compile(r"^[a-z]+(_[a-z]+)+$")
METHODS = {"get", "post", "put", "patch", "delete"}


def operations(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        operation
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in METHODS
    ]


def print_schema() -> bytes:
    return subprocess.run(
        [sys.executable, "-m", "labhq.api.openapi"], check=True, capture_output=True
    ).stdout


def test_the_printed_schema_is_byte_identical_across_runs() -> None:
    first, second = print_schema(), print_schema()
    assert first == second
    assert json.loads(first)["paths"]


def test_every_operation_has_a_stable_area_verb_operation_id() -> None:
    schema = json.loads(render())
    ids = [operation.get("operationId", "") for operation in operations(schema)]
    assert ids
    assert all(OPERATION_ID.match(value) for value in ids), ids
    assert len(ids) == len(set(ids))
    assert len(list(default_routers)) >= 1


def test_operation_ids_and_errors_come_from_the_registry_not_the_path() -> None:
    router = APIRouter(prefix="/approvals")

    @router.get("/{approval_id}")
    async def approvals_get(
        owner: OwnerDep, approval_id: int, verbose: Annotated[bool, Query()] = False
    ) -> int:
        return approval_id

    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(router)
    schema = create_app(routers=routers).openapi()
    operation = schema["paths"]["/api/approvals/{approval_id}"]["get"]
    assert operation["operationId"] == "approvals_get"
    # Errors, validation included, are declared in the one envelope the server sends.
    assert set(operation["responses"]) == {"200", "default"}
    error = operation["responses"]["default"]["content"]["application/json"]["schema"]
    assert error == {"$ref": "#/components/schemas/ErrorEnvelope"}
    assert "HTTPValidationError" not in schema["components"]["schemas"]
