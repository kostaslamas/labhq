"""`/api/push`: the VAPID public key, and subscribing or unsubscribing this browser.

Subscribing needs a signed-in passkey session: a subscriber receives the text of every
approval. Nothing here logs an endpoint or a key.
"""

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.auth.routes import SignedIn
from labhq.notify import subscriptions
from labhq.notify.settings import get_notify_settings
from labhq.notify.vapid import application_server_key, load_or_create_vapid

router = APIRouter(prefix="/push", tags=["push"])


class PushStatus(BaseModel):
    # What `pushManager.subscribe` takes as `applicationServerKey`.
    public_key: str
    # Whether Web Push is the notifier in use; a device can still subscribe when it is not.
    active: bool


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class SubscribeBody(BaseModel):
    """`PushSubscription.toJSON()` as the browser gives it."""

    endpoint: str = Field(min_length=1, max_length=2048, pattern=r"^https://")
    keys: PushKeys


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


@router.get("/status")
async def push_status(context: ContextDep) -> PushStatus:
    vapid = load_or_create_vapid(context.settings.data_dir)
    return PushStatus(
        public_key=application_server_key(vapid),
        active=get_notify_settings().kind == "webpush",
    )


@router.post("/subscriptions", status_code=204)
async def push_subscribe(
    body: SubscribeBody, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> Response:
    await subscriptions.save(
        db, clock.now(), endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/subscriptions/remove", status_code=204)
async def push_unsubscribe(body: UnsubscribeBody, owner: SignedIn, db: SessionDep) -> Response:
    await subscriptions.remove(db, body.endpoint)
    await db.commit()
    return Response(status_code=204)
