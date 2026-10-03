import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest

from labhq.approvals import ApprovalService
from labhq.approvals.gates import (
    GateAnswer,
    GateError,
    GateRelay,
    GateRequest,
    GateSettings,
    GateStatus,
    build_gate,
    gate_adapters,
)
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval
from tests.approvals.conftest import World

TOKEN = "s3cret-token-value"
HEAVY = "delete_branch"
LIGHT = "assign_task"


@dataclass
class FakeGateServer:
    """Plays the gate over `httpx.MockTransport`; tests set what status answers."""

    answer: dict[str, str] = field(default_factory=lambda: {"status": "pending"})
    seen: list[httpx.Request] = field(default_factory=list)
    fail_with: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.fail_with is not None:
            # A gate that echoes the credential back, to prove errors never repeat bodies.
            return httpx.Response(self.fail_with, text=f"echo {TOKEN}")
        if request.method == "POST":
            return httpx.Response(200, json={"id": "req-1"})
        return httpx.Response(200, json=self.answer)

    @property
    def posts(self) -> list[httpx.Request]:
        return [r for r in self.seen if r.method == "POST"]

    @property
    def gets(self) -> list[httpx.Request]:
        return [r for r in self.seen if r.method == "GET"]


def settings(**overrides: object) -> GateSettings:
    fields: dict[str, object] = {"base_url": "https://gate.example", "token": TOKEN, "name": "demo"}
    return GateSettings(**{**fields, **overrides})  # type: ignore[arg-type]


def relay_for(world: World, config: GateSettings, client: httpx.AsyncClient) -> GateRelay:
    return GateRelay(
        world.sessions,
        world.service,
        build_gate(config, client),
        name=config.name,
        passkey_proofs=config.proofs,
    )


@pytest.fixture
def server() -> FakeGateServer:
    return FakeGateServer()


@pytest.fixture
async def relay(world: World, server: FakeGateServer) -> AsyncIterator[GateRelay]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        yield relay_for(world, settings(), client)


async def request(world: World, action: str = HEAVY) -> Approval:
    return await world.service.request(action, {"branch": "labhq/task-1"}, task_id=world.task_id)


async def test_a_heavy_approval_is_posted_then_resolved_on_a_passkey_proof(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    approval = await request(world)
    await relay.run_once()

    assert len(server.posts) == 1
    post = server.posts[0]
    assert post.url.path == "/internal/request"
    assert post.headers["X-Gate-Token"] == TOKEN
    body = json.loads(post.content)
    assert body["command"] == f"{HEAVY} branch=labhq/task-1"
    assert body["cwd"]
    assert (await world.service.get(approval.id)).gate == {
        "name": "demo",
        "request_id": "req-1",
        "state": "sent",
    }

    server.answer = {"status": "approved", "via": "face_id"}
    await relay.run_once()

    done = await world.service.get(approval.id)
    assert done.status is ApprovalStatus.APPROVED
    assert done.decided_by == "gate:demo"
    assert done.confirmation_kind == "external_gate"
    assert server.seen[-1].url.path == "/internal/status/req-1"


async def test_pending_keeps_polling_without_a_second_post(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    await request(world)
    for _ in range(3):
        await relay.run_once()
    assert len(server.posts) == 1
    assert len(server.gets) == 2


async def test_a_password_approval_leaves_it_pending_and_records_why(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    approval = await request(world)
    await relay.run_once()
    server.answer = {"status": "approved", "via": "password"}
    await relay.run_once()
    await relay.run_once()

    row = await world.service.get(approval.id)
    assert row.status is ApprovalStatus.PENDING
    assert row.gate is not None
    assert row.gate["state"] == "insufficient_proof"
    assert "password" in row.gate["note"]
    # A stalled request is not polled again.
    assert len(server.gets) == 1


async def test_a_denial_rejects_the_approval(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    approval = await request(world)
    await relay.run_once()
    server.answer = {"status": "denied", "via": "passkey"}
    await relay.run_once()

    row = await world.service.get(approval.id)
    assert row.status is ApprovalStatus.REJECTED
    assert row.decided_by == "gate:demo"


async def test_an_expiry_leaves_it_pending_and_resend_posts_again(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    approval = await request(world)
    await relay.run_once()
    server.answer = {"status": "expired"}
    await relay.run_once()

    row = await world.service.get(approval.id)
    assert row.status is ApprovalStatus.PENDING
    assert row.gate is not None
    assert row.gate["state"] == "expired"

    await relay.resend(approval.id)
    await relay.run_once()
    assert len(server.posts) == 2


async def test_resend_refuses_a_request_that_is_still_live(world: World, relay: GateRelay) -> None:
    approval = await request(world)
    await relay.run_once()
    with pytest.raises(GateError):
        await relay.resend(approval.id)


async def test_light_approvals_never_reach_the_gate(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    light = await request(world, LIGHT)
    await relay.run_once()

    assert server.seen == []
    assert (await world.service.get(light.id)).gate is None


async def test_the_token_is_in_no_log_row_or_error(
    world: World, relay: GateRelay, server: FakeGateServer, caplog: pytest.LogCaptureFixture
) -> None:
    approval = await request(world)
    with caplog.at_level(logging.DEBUG):
        server.fail_with = 500
        await relay.run_once()
        server.fail_with = None
        await relay.run_once()
        server.answer = {"status": "approved", "via": "password"}
        await relay.run_once()

    assert "HTTP 500" in caplog.text
    assert TOKEN not in caplog.text
    row = await world.service.get(approval.id)
    assert TOKEN not in json.dumps([row.gate, row.payload, row.decision_note])
    assert TOKEN not in repr(settings())

    server.fail_with = 401
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        with pytest.raises(GateError) as caught:
            await build_gate(settings(), client).send(GateRequest("x", ""))
    assert TOKEN not in str(caught.value)
    assert "401" in str(caught.value)


async def test_a_gate_outage_changes_nothing_and_is_retried(
    world: World, relay: GateRelay, server: FakeGateServer
) -> None:
    approval = await request(world)
    server.fail_with = 503
    assert await relay.run_once() == 0
    assert (await world.service.get(approval.id)).gate is None

    server.fail_with = None
    assert await relay.run_once() == 1
    assert (await world.service.get(approval.id)).gate is not None


async def test_paths_header_and_proofs_are_settings(world: World, server: FakeGateServer) -> None:
    config = settings(
        token_header="X-Other",
        request_path="/r",
        status_path="/s/{id}/now",
        passkey_proofs="hardware_key",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        relay = relay_for(world, config, client)
        approval = await request(world)
        await relay.run_once()
        server.answer = {"status": "approved", "via": "hardware_key"}
        await relay.run_once()

    assert server.seen[0].url.path == "/r"
    assert server.seen[0].headers["X-Other"] == TOKEN
    assert server.seen[1].url.path == "/s/req-1/now"
    assert (await world.service.get(approval.id)).status is ApprovalStatus.APPROVED


async def test_a_new_gate_kind_is_a_registration(world: World) -> None:
    class DummyGate:
        def __init__(self) -> None:
            self.sent: list[GateRequest] = []

        async def send(self, request: GateRequest) -> str:
            self.sent.append(request)
            return "d-1"

        async def status(self, request_id: str) -> GateAnswer:
            return GateAnswer(GateStatus.APPROVED, "passkey")

    dummy = DummyGate()
    gate_adapters.register("dummy", lambda *_: dummy)
    try:
        config = GateSettings(kind="dummy", name="dummy")
        service = ApprovalService(world.sessions, clock=world.clock)
        async with httpx.AsyncClient() as client:
            relay = GateRelay(
                world.sessions,
                service,
                build_gate(config, client),
                name="dummy",
                passkey_proofs=config.proofs,
            )
            approval = await request(world)
            await relay.run_once()
            await relay.run_once()
    finally:
        gate_adapters._entries.pop("dummy")

    assert len(dummy.sent) == 1
    assert (await world.service.get(approval.id)).decided_by == "gate:dummy"
