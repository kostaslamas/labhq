"""Web Push: signed pushes to every subscription, pruning of gone ones, the key file."""

import base64
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from requests.adapters import BaseAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.enums import NotificationStatus
from labhq.db.models import PushSubscription
from labhq.notify import Dispatcher, Message, NotifyError, NotifySettings, build_notifier
from labhq.notify.vapid import KEY_FILENAME, application_server_key, load_or_create_vapid
from labhq.notify.webpush import WebPushNotifier
from tests.approvals.conftest import World
from tests.notify.conftest import all_rows

SUBJECT = "https://example.test"
SEND = "https://push.example.test/send/"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class PushService(BaseAdapter):
    """A requests adapter that is the push service: it records pushes and answers by endpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.pushes: list[requests.PreparedRequest] = []
        self.answers: dict[str, int] = {}

    def send(
        self, request: requests.PreparedRequest, *args: Any, **kwargs: Any
    ) -> requests.Response:
        self.pushes.append(request)
        response = requests.Response()
        response.status_code = self.answers.get(str(request.url), 201)
        response.url = str(request.url)
        response.request = request
        return response

    def close(self) -> None:
        return None

    def session(self) -> requests.Session:
        session = requests.Session()
        session.mount("https://", self)
        return session


@pytest.fixture
def push_service() -> PushService:
    return PushService()


def new_subscription(label: str) -> dict[str, str]:
    """What a browser hands over: an endpoint and a real P-256 key with an auth secret."""
    point = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )
    return {"endpoint": SEND + label, "p256dh": b64(point), "auth": b64(os.urandom(16))}


async def subscribe(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, *labels: str
) -> None:
    async with sessions() as db:
        for label in labels:
            db.add(PushSubscription(created_at=clock.now(), **new_subscription(label)))
        await db.commit()


def notifier_for(
    sessions: async_sessionmaker[AsyncSession], data_dir: Path, service: PushService
) -> WebPushNotifier:
    return WebPushNotifier(
        sessions,
        load_or_create_vapid(data_dir),
        subject=SUBJECT,
        ttl_seconds=60,
        session=service.session(),
    )


def verify_vapid_signature(request: requests.PreparedRequest, public_key: str) -> dict[str, Any]:
    """Check the ES256 signature of the VAPID JWT against the stored public key."""
    header = str(request.headers["Authorization"])
    assert header.startswith("vapid ")
    parts = dict(item.strip().split("=", 1) for item in header.removeprefix("vapid ").split(","))
    assert parts["k"] == public_key
    head, claims, signature = parts["t"].split(".")
    raw = b64decode(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64decode(public_key))
    key.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    decoded: dict[str, Any] = json.loads(b64decode(claims))
    return decoded


async def test_a_new_approval_sends_one_signed_push_to_every_subscription(
    world: World, clock: FakeClock, push_service: PushService, tmp_path: Path
) -> None:
    await subscribe(world.sessions, clock, "phone", "tablet")
    notifier = notifier_for(world.sessions, tmp_path, push_service)
    settings = NotifySettings()
    assert settings.kind == "webpush"

    approval = await world.service.request("delete_branch", {"members": ["a"], "lead": "m"})
    dispatcher = Dispatcher(world.sessions, notifier, clock=clock, settings=settings)
    assert await dispatcher.dispatch_pending() == 1

    assert sorted(str(r.url) for r in push_service.pushes) == [SEND + "phone", SEND + "tablet"]
    public_key = application_server_key(load_or_create_vapid(tmp_path))
    for request in push_service.pushes:
        claims = verify_vapid_signature(request, public_key)
        assert claims["sub"] == SUBJECT
        assert claims["aud"] == "https://push.example.test"
        assert request.headers["TTL"] == "60"
        assert request.headers["Content-Encoding"] == "aes128gcm"
        # The body is encrypted for the browser, so the approval text is not readable in transit.
        assert f"A{approval.id}".encode() not in (request.body or b"")
    assert (await all_rows(world.sessions))[0].status == NotificationStatus.SENT


async def test_a_gone_subscription_is_pruned_and_the_others_still_receive(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    push_service: PushService,
    tmp_path: Path,
) -> None:
    await subscribe(sessions, clock, "gone", "expired", "alive")
    push_service.answers = {SEND + "gone": 410, SEND + "expired": 404}
    notifier = notifier_for(sessions, tmp_path, push_service)

    await notifier.send(Message("Title", "Body", "/approve/1"))

    assert len(push_service.pushes) == 3
    async with sessions() as db:
        left = list(await db.scalars(select(PushSubscription.endpoint)))
    assert left == [SEND + "alive"]


async def test_a_transient_failure_is_retried_and_keeps_the_subscription(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    push_service: PushService,
    tmp_path: Path,
) -> None:
    await subscribe(sessions, clock, "down")
    push_service.answers = {SEND + "down": 503}
    notifier = notifier_for(sessions, tmp_path, push_service)
    with pytest.raises(NotifyError, match="503") as failure:
        await notifier.send(Message("Title", "Body"))
    assert "push.example.test" not in str(failure.value)
    async with sessions() as db:
        assert len(list(await db.scalars(select(PushSubscription)))) == 1

    # Delivered to one device is a success: a retry would push to the others twice.
    await subscribe(sessions, clock, "up")
    await notifier.send(Message("Title", "Body"))


async def test_no_subscription_is_an_error_the_outbox_retries(
    sessions: async_sessionmaker[AsyncSession], push_service: PushService, tmp_path: Path
) -> None:
    notifier = notifier_for(sessions, tmp_path, push_service)
    with pytest.raises(NotifyError, match="no device"):
        await notifier.send(Message("Title", "Body"))


def test_the_vapid_key_file_is_private_and_stable(tmp_path: Path) -> None:
    first = application_server_key(load_or_create_vapid(tmp_path / "data"))
    path = tmp_path / "data" / KEY_FILENAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert application_server_key(load_or_create_vapid(tmp_path / "data")) == first


async def test_the_private_key_and_endpoints_never_reach_the_logs(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    push_service: PushService,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    await subscribe(sessions, clock, "secret-device", "gone")
    push_service.answers = {SEND + "gone": 410}
    notifier = notifier_for(sessions, tmp_path, push_service)
    await notifier.send(Message("Title", "Body"))

    pem = (tmp_path / KEY_FILENAME).read_text()
    body = "".join(line for line in pem.splitlines() if "-----" not in line)
    assert body not in caplog.text
    assert "secret-device" not in caplog.text
    assert "push.example.test" not in caplog.text


def test_the_registration_needs_the_database_for_subscriptions(tmp_path: Path) -> None:
    with pytest.raises(NotifyError, match="database"):
        build_notifier(NotifySettings(), httpx.AsyncClient(), tmp_path)
