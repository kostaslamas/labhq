"""`GET /api/vocabulary`: every status enum of `labhq.db.enums`, so they reach the OpenAPI.

The response model is built from the module, not written out: a new `...Status` enum becomes
a new field, the generated TypeScript client gains it, and `web/src/api/status.ts` stops
type-checking until the UI maps it.
"""

import re
from enum import StrEnum
from types import GenericAlias
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, create_model

from labhq.db import enums

STATUS_SUFFIX = "Status"


def status_enums() -> dict[str, type[StrEnum]]:
    """`{"run_status": RunStatus, ...}` for every enum in `labhq.db.enums` named `*Status`."""
    found = {
        snake_case(name): value
        for name, value in vars(enums).items()
        if isinstance(value, type)
        and issubclass(value, StrEnum)
        and value is not StrEnum
        and name.endswith(STATUS_SUFFIX)
    }
    return dict(sorted(found.items()))


def snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _model() -> type[BaseModel]:
    fields: dict[str, Any] = {
        key: (GenericAlias(list, enum), Field(description=f"Every value of `{enum.__name__}`."))
        for key, enum in status_enums().items()
    }
    return create_model(
        "Vocabulary",
        __config__=ConfigDict(frozen=True),
        __doc__="The status values the backend may return, by enum.",
        **fields,
    )


Vocabulary = _model()

vocabulary_router = APIRouter(tags=["vocabulary"])


@vocabulary_router.get("/vocabulary", response_model=Vocabulary)
async def vocabulary_get() -> BaseModel:
    """The backend's status values; the UI maps each one onto its own states."""
    return Vocabulary(**{key: list(enum) for key, enum in status_enums().items()})
