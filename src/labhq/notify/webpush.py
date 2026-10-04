"""Web Push: one signed, encrypted push to every stored subscription.

The push service answers 404 or 410 once a subscription is gone; that row is deleted and the
others still receive. Nothing here logs or raises a subscription endpoint or a key: a failed
push is reported by status code only, because the library's own text may carry a response body.
"""

import asyncio
import json
from dataclasses import dataclass

import requests
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.db.models import PushSubscription
from labhq.notify.base import Message, NotifyError

GONE_STATUSES = frozenset({404, 410})
# A push payload is limited to about 4 KB after encryption; approval text can be longer.
MAX_BODY_CHARS = 1000
TIMEOUT_SECONDS = 10
DELIVERED = 201


@dataclass(frozen=True)
class Target:
    id: int
    info: dict[str, object]


def payload_of(message: Message) -> str:
    return json.dumps(
        {
            "title": message.title,
            "body": message.body[:MAX_BODY_CHARS],
            "click_url": message.click_url,
        }
    )


class WebPushNotifier:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        vapid: Vapid02,
        *,
        subject: str,
        ttl_seconds: int,
        session: requests.Session | None = None,
    ) -> None:
        self._sessions = sessions
        self._vapid = vapid
        self._claims = {"sub": subject}
        self._ttl = ttl_seconds
        self._session = session

    async def send(self, message: Message) -> None:
        async with self._sessions() as db:
            rows = (await db.execute(select(PushSubscription))).scalars().all()
            targets = [
                Target(
                    row.id,
                    {"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}},
                )
                for row in rows
            ]
        if not targets:
            raise NotifyError("no device has enabled Web Push yet")
        payload = payload_of(message)
        statuses = await asyncio.gather(*(self._push(target, payload) for target in targets))
        gone = [
            t.id for t, status in zip(targets, statuses, strict=True) if status in GONE_STATUSES
        ]
        if gone:
            async with self._sessions() as db:
                await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
                await db.commit()
        # Delivered to someone: a retry would push the same message twice to that device.
        if any(status is not None and status < 300 for status in statuses):
            return
        if len(gone) == len(targets):
            raise NotifyError("every Web Push subscription was gone and has been removed")
        codes = sorted({str(status) if status else "unreachable" for status in statuses})
        raise NotifyError("web push failed: " + ", ".join(codes))

    async def _push(self, target: Target, payload: str) -> int | None:
        """The HTTP status the push service answered, or None when it could not be reached."""
        try:
            await asyncio.to_thread(self._post, target, payload)
        except WebPushException as error:
            return None if error.response is None else error.response.status_code
        except requests.RequestException:
            return None
        return DELIVERED

    def _post(self, target: Target, payload: str) -> None:
        webpush(
            target.info,
            payload,
            vapid_private_key=self._vapid,
            vapid_claims=dict(self._claims),
            ttl=self._ttl,
            timeout=TIMEOUT_SECONDS,
            requests_session=self._session,
        )
