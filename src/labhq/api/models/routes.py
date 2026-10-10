"""The Models page: which model and effort each role and task kind uses, and its cost.

Saving the table changes what every agent costs, so it needs a fresh passkey assertion
(purpose `models:policy`, issued by `/auth/step-up/options`), like the other settings.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from labhq.api.channels.routes import prove
from labhq.api.deps import ClockDep, SessionDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.modelpolicy import CATALOG, EFFORTS, ROLE_KEYS, PolicyError, load_policy, save_policy
from labhq.modelpolicy.report import cost_by_model

router = APIRouter(prefix="/models", tags=["models"])

PURPOSE = "models:policy"


class ModelOut(BaseModel):
    id: str
    display_name: str
    input_micros_per_mtok: int
    output_micros_per_mtok: int


class RowOut(BaseModel):
    key: str
    kind: str
    model: str
    effort: str
    max_output_tokens: int | None


class PolicyOut(BaseModel):
    models: list[ModelOut]
    efforts: list[str]
    rows: list[RowOut]


class RowIn(BaseModel):
    model: str
    effort: str
    max_output_tokens: int | None = None


class PolicyIn(BaseModel):
    rows: dict[str, RowIn]
    credential: dict[str, object] | None = None


class CostOut(BaseModel):
    model: str
    runs: int
    cost_micros: int
    input_tokens: int
    output_tokens: int
    reference_micros: int | None
    saved_micros: int | None


async def policy_out(db: SessionDep) -> PolicyOut:
    policy = await load_policy(db)
    return PolicyOut(
        models=[
            ModelOut(
                id=m.id,
                display_name=m.display_name,
                input_micros_per_mtok=m.input_micros_per_mtok,
                output_micros_per_mtok=m.output_micros_per_mtok,
            )
            for m in CATALOG
        ],
        efforts=list(EFFORTS),
        rows=[
            RowOut(
                key=key,
                kind="role" if key in ROLE_KEYS else "task",
                model=row.model,
                effort=row.effort,
                max_output_tokens=row.max_output_tokens,
            )
            for key, row in policy.rows.items()
        ],
    )


@router.get("")
async def models_get(owner: SignedIn, db: SessionDep) -> PolicyOut:
    return await policy_out(db)


@router.put("")
async def models_put(
    body: PolicyIn, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> PolicyOut:
    """Save rows over the stored table. An unknown model or effort changes nothing."""
    await prove(request, db, clock, owner, PURPOSE, body.credential)
    try:
        await save_policy(db, clock, {key: row.model_dump() for key, row in body.rows.items()})
    except PolicyError as error:
        await db.rollback()
        raise ApiError(422, "model_policy_invalid", str(error)) from None
    return await policy_out(db)


@router.get("/usage")
async def models_usage(
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[CostOut]:
    """Cost by model over the last `days`, in micro-USD, with what the policy saved."""
    rows = await cost_by_model(db, since=clock.now() - timedelta(days=days))
    return [
        CostOut(
            model=r.model,
            runs=r.runs,
            cost_micros=r.cost_micros,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            reference_micros=r.reference_micros,
            saved_micros=r.saved_micros,
        )
        for r in rows
    ]
