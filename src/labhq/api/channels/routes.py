"""The Channels page: list, add, test and remove the places the owner is notified.

Adding, removing and switching a channel change where alerts and login links go, so each needs
a fresh passkey assertion (purpose `channel:new` or `channel:<id>`, issued by
`/auth/step-up/options`). Sending a test message changes nothing and needs only the session.
A secret (a bot token) comes in on the add request over the owner's own session, is written
owner-only and is never returned.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.auth import AuthError, get_auth_settings, verify_step_up
from labhq.auth.routes import SignedIn, origin_of
from labhq.channels import (
    ChannelConfigError,
    ChannelNotFoundError,
    ChannelRuntime,
    channel_kinds,
    get_channel,
    list_channels,
    remove_channel,
    set_enabled,
)
from labhq.channels.setup import create_and_test
from labhq.chat.registry import configured_chat_adapters
from labhq.db.models import NotificationChannel
from labhq.notify import NotifySettings

router = APIRouter(prefix="/channels", tags=["channels"])

HTTP_TIMEOUT_SECONDS = 10.0
CHAT_KINDS = ("discord", "slack")


class ChannelOut(BaseModel):
    id: int
    name: str
    kind: str
    enabled: bool
    last_test_ok: bool | None
    last_test_error: str | None
    last_tested_at: datetime | None


class FieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    default: str | None


class KindOut(BaseModel):
    kind: str
    label: str
    fields: list[FieldOut]
    # False for a chat service whose bot is not set up on this machine.
    available: bool


class AddBody(BaseModel):
    kind: str
    name: str = Field(max_length=64)
    values: dict[str, str] = Field(default_factory=dict)
    credential: dict[str, Any] | None = None


class SwitchBody(BaseModel):
    enabled: bool
    credential: dict[str, Any] | None = None


class RemoveBody(BaseModel):
    credential: dict[str, Any] | None = None


class Tested(BaseModel):
    channel: ChannelOut
    # None when the test message arrived.
    error: str | None


def out(row: NotificationChannel) -> ChannelOut:
    return ChannelOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        enabled=row.enabled,
        last_test_ok=row.last_test_ok,
        last_test_error=row.last_test_error,
        last_tested_at=row.last_tested_at,
    )


async def get_runtime(context: ContextDep, clock: ClockDep) -> AsyncIterator[ChannelRuntime]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        yield ChannelRuntime(
            context.sessions, client, context.settings.data_dir, clock, NotifySettings()
        )


RuntimeDep = Annotated[ChannelRuntime, Depends(get_runtime)]


async def prove(
    request: Request,
    db: SessionDep,
    clock: ClockDep,
    owner: SignedIn,
    purpose: str,
    credential: dict[str, Any] | None,
) -> None:
    """Accept the passkey assertion for `purpose`, or raise 403 and change nothing."""
    if credential is None:
        raise ApiError(403, "step_up_required", "This change needs your passkey.")
    try:
        await verify_step_up(
            db,
            clock.now(),
            session_id=owner.session_id,
            purpose=purpose,
            assertion=credential,
            origin=origin_of(request),
            settings=get_auth_settings(),
        )
    except AuthError as error:
        # The spent challenge stays spent. A 403 and not the auth 401, which signs the UI out.
        await db.commit()
        raise ApiError(403, error.code, error.message) from None


def not_found(channel_id: int) -> ApiError:
    return ApiError(404, "channel_not_found", f"No channel {channel_id}.")


@router.get("")
async def channels_list(owner: SignedIn, db: SessionDep) -> list[ChannelOut]:
    return [out(row) for row in await list_channels(db)]


@router.get("/kinds")
async def channels_kinds(owner: SignedIn) -> list[KindOut]:
    chat = configured_chat_adapters()
    return [
        KindOut(
            kind=name,
            label=definition.label,
            fields=[
                FieldOut(name=f.name, label=f.label, secret=f.secret, default=f.default)
                for f in definition.fields
            ],
            available=name in chat if name in CHAT_KINDS else True,
        )
        for name in channel_kinds
        for definition in [channel_kinds.get(name)]
    ]


@router.post("", status_code=201)
async def channels_add(
    body: AddBody,
    request: Request,
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
    context: ContextDep,
    runtime: RuntimeDep,
) -> Tested:
    """Add a channel with a passkey, send its test message and show how that went."""
    await prove(request, db, clock, owner, "channel:new", body.credential)
    await db.commit()
    try:
        row, error = await create_and_test(
            context.sessions,
            runtime,
            context.settings.data_dir,
            clock,
            kind=body.kind,
            name=body.name,
            values=body.values,
        )
    except ChannelConfigError as refusal:
        raise ApiError(422, "channel_invalid", str(refusal)) from None
    return Tested(channel=out(row), error=error)


@router.post("/{channel_id}/test")
async def channels_test(channel_id: int, owner: SignedIn, runtime: RuntimeDep) -> Tested:
    try:
        error = await runtime.test(channel_id)
    except ChannelNotFoundError:
        raise not_found(channel_id) from None
    async with runtime.sessions() as db:
        return Tested(channel=out(await get_channel(db, channel_id)), error=error)


@router.patch("/{channel_id}")
async def channels_switch(
    channel_id: int,
    body: SwitchBody,
    request: Request,
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
) -> ChannelOut:
    await prove(request, db, clock, owner, f"channel:{channel_id}", body.credential)
    try:
        row = await set_enabled(db, channel_id, body.enabled)
    except ChannelNotFoundError:
        await db.commit()
        raise not_found(channel_id) from None
    await db.commit()
    return out(row)


@router.delete("/{channel_id}", status_code=204)
async def channels_remove(
    channel_id: int,
    body: RemoveBody,
    request: Request,
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
    context: ContextDep,
) -> None:
    await prove(request, db, clock, owner, f"channel:{channel_id}", body.credential)
    try:
        await remove_channel(db, context.settings.data_dir, channel_id)
    except ChannelNotFoundError:
        await db.commit()
        raise not_found(channel_id) from None
    await db.commit()
