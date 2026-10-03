"""Approvals over HTTP. Every decision goes through `ApprovalService`; the API never executes.

A light approve with a session is a tap. A heavy approve needs a passkey assertion for
`approval:{id}`, checked in the same transaction that records the decision. Anything less is
a 403 and the approval stays pending.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import and_, case, or_, select

from labhq.api.approvals.schemas import ApprovalOut, DecisionBody, describe
from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.pagination import Page, PageParamsDep, decode_cursor, encode_cursor
from labhq.approvals import (
    ApprovalError,
    ApprovalNotFoundError,
    ApprovalNotPendingError,
    ApprovalService,
    ConfirmationNotAllowedError,
)
from labhq.auth import AuthError, begin_step_up, get_auth_settings, verify_step_up
from labhq.auth.routes import Options, SignedIn, origin_of
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval

router = APIRouter(prefix="/approvals", tags=["approvals"])

TAP = "tap"
PASSKEY = "passkey"
# Pending first, then everything settled; inside each group newest first.
pending_rank = case((Approval.status == ApprovalStatus.PENDING, 0), else_=1)

IdempotencyKey = Annotated[
    str,
    Header(min_length=1, max_length=128, description="One per user intent; a retry reuses it."),
]


def purpose_of(approval_id: int) -> str:
    return f"approval:{approval_id}"


def not_found(approval_id: int) -> ApiError:
    return ApiError(404, "approval_not_found", f"There is no approval {approval_id}.")


def already_decided(approval_id: int) -> ApiError:
    return ApiError(409, "approval_not_pending", f"Approval {approval_id} is already decided.")


async def load(db: SessionDep, approval_id: int) -> Approval:
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise not_found(approval_id)
    return approval


@router.get("")
async def approvals_list(
    db: SessionDep,
    params: PageParamsDep,
    status: Annotated[ApprovalStatus | None, Query(description="Only this status.")] = None,
) -> Page[ApprovalOut]:
    """Pending approvals first, then the settled ones, each group newest first."""
    statement = select(Approval)
    if status is not None:
        statement = statement.where(Approval.status == status)
    if params.cursor is not None:
        rank, last_id = decode_cursor(params.cursor, 2)
        statement = statement.where(
            or_(pending_rank > rank, and_(pending_rank == rank, Approval.id < last_id))
        )
    statement = statement.order_by(pending_rank, Approval.id.desc()).limit(params.limit + 1)
    rows = list((await db.scalars(statement)).all())
    next_cursor = None
    if len(rows) > params.limit:
        rows = rows[: params.limit]
        last = rows[-1]
        next_cursor = encode_cursor([0 if last.status == ApprovalStatus.PENDING else 1, last.id])
    return Page(items=[await describe(db, row) for row in rows], next_cursor=next_cursor)


@router.get("/{approval_id}")
async def approvals_get(approval_id: int, db: SessionDep) -> ApprovalOut:
    return await describe(db, await load(db, approval_id))


@router.post("/{approval_id}/step-up")
async def approvals_step_up(
    approval_id: int, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> Options:
    """A passkey challenge bound to this approval and this session."""
    if (await load(db, approval_id)).status != ApprovalStatus.PENDING:
        raise already_decided(approval_id)
    try:
        options = await begin_step_up(
            db,
            clock.now(),
            session_id=owner.session_id,
            purpose=purpose_of(approval_id),
            origin=origin_of(request),
            settings=get_auth_settings(),
        )
    except AuthError as error:
        raise ApiError(error.status_code, error.code, error.message) from None
    await db.commit()
    return options


async def prove_heavy(
    db: SessionDep,
    request: Request,
    clock: ClockDep,
    session_id: int,
    approval_id: int,
    body: DecisionBody,
) -> None:
    """Check the passkey assertion in `db`; the decision commits it, a refusal rolls it back."""
    if body.credential is None:
        raise ApiError(403, "step_up_required", "A heavy approval needs a passkey.")
    try:
        await verify_step_up(
            db,
            clock.now(),
            session_id=session_id,
            purpose=purpose_of(approval_id),
            assertion=body.credential,
            origin=origin_of(request),
            settings=get_auth_settings(),
        )
    except AuthError as error:
        # The spent challenge stays spent: a failed assertion is never retried. A 403 and not
        # the auth 401, which would sign the UI out.
        await db.commit()
        raise ApiError(403, error.code, error.message) from None


async def settle(
    service: ApprovalService,
    db: SessionDep,
    approval: Approval,
    body: DecisionBody,
    decider: str,
    key: str,
    prove: Callable[[], Awaitable[None]],
) -> None:
    if body.decision == "reject":
        # Saying no never needs a passkey (policy: any registered kind may refuse).
        await service.reject(
            approval.id, decider=decider, confirmation=TAP, note=body.note, idempotency_key=key
        )
        return
    heavy = approval.risk_class == RiskClass.HEAVY
    if heavy:
        await prove()
    await service.approve(
        approval.id,
        decider=decider,
        confirmation=PASSKEY if heavy else TAP,
        note=body.note,
        idempotency_key=key,
        within=db if heavy else None,
    )


@router.post("/{approval_id}/decision")
async def approvals_decide(
    approval_id: int,
    body: DecisionBody,
    request: Request,
    owner: SignedIn,
    db: SessionDep,
    context: ContextDep,
    clock: ClockDep,
    idempotency_key: IdempotencyKey,
) -> ApprovalOut:
    """Approve or reject. A repeated key answers with the decision it already made."""
    approval = await load(db, approval_id)
    if approval.decision_key == idempotency_key:
        return await describe(db, approval)
    if approval.status != ApprovalStatus.PENDING:
        raise already_decided(approval_id)

    async def prove() -> None:
        await prove_heavy(db, request, clock, owner.session_id, approval_id, body)

    service = ApprovalService(context.sessions, clock=context.clock)
    try:
        await settle(service, db, approval, body, f"web:{owner.subject}", idempotency_key, prove)
    except ApprovalNotPendingError:
        # Lost a race: a retry of the same intent is answered, anything else is a conflict.
        await db.rollback()
        decided = await load(db, approval_id)
        if decided.decision_key == idempotency_key:
            return await describe(db, decided)
        raise already_decided(approval_id) from None
    except ApprovalNotFoundError:
        raise not_found(approval_id) from None
    except ConfirmationNotAllowedError as error:
        raise ApiError(403, "confirmation_not_allowed", str(error)) from None
    except ApprovalError as error:
        raise ApiError(409, "approval_failed", str(error)) from None
    # The engine wrote on other connections; end this session's snapshot before reading back.
    await db.rollback()
    return await describe(db, await load(db, approval_id))
