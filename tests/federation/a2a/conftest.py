"""Two instances paired over A2A: A sends to B's in-process ASGI app, B never dials A."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.settings import ApiSettings
from labhq.clock import FakeClock
from labhq.db.models import FederationNode
from labhq.federation.a2a.client import NodeA2aClient
from labhq.federation.a2a.sync import SyncResult, sync_once
from labhq.federation.invites import Invites
from labhq.federation.nodes import Nodes
from labhq.federation.queue import DatabaseOrderQueue
from labhq.federation.settings import FederationSettings
from tests.federation.conftest import NODE_NAME, Instance, _build

NODE_URL = "http://lab-b.test"
A2A_URL = f"{NODE_URL}/api/federation/a2a"
UPSTREAM_LABEL = "Lab A"


class RecordingTransport(httpx.AsyncBaseTransport):
    """Forwards to B's app and notes each JSON-RPC method A calls, in order."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.methods: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/federation/a2a") and request.method == "POST":
            self.methods.append(json.loads(request.content)["method"])
        return await self._inner.handle_async_request(request)


@dataclass
class Link:
    """What A needs to reach B: the keys it holds and the transport to B's app."""

    settings: FederationSettings
    transport: RecordingTransport | None = None
    dialled: list[str] = field(default_factory=list)

    def make_client(self, node: FederationNode, key: str) -> NodeA2aClient:
        assert node.a2a_url is not None
        assert self.transport is not None
        self.dialled.append(node.name)
        return NodeA2aClient(node.a2a_url, key, timeout=5, transport=self.transport)


@pytest.fixture
def link() -> Link:
    return Link(FederationSettings())


@pytest.fixture
async def upstream(upstream_url: str, clock: FakeClock, link: Link) -> AsyncIterator[Instance]:
    def queue(sessions: async_sessionmaker[AsyncSession], at: FakeClock) -> DatabaseOrderQueue:
        return DatabaseOrderQueue(
            sessions, at, settings=link.settings, make_client=link.make_client
        )

    async for instance in _build("upstream", upstream_url, clock, True, queue):
        yield instance


@dataclass
class A2aPairing:
    upstream: Instance
    downstream: Instance
    link: Link
    key: str
    node_id: int
    remote_manager: int

    def app(self):
        return create_app(
            self.downstream.context,
            resolvers=ResolverRegistry(),
            settings=ApiSettings(ui_dir=Path("/nonexistent")),
        )

    def http(self, key: str | None = None) -> httpx.AsyncClient:
        headers = {"A2A-Version": "1.0"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return httpx.AsyncClient(transport=self.link.transport, base_url=NODE_URL, headers=headers)

    async def sync(self) -> SyncResult:
        return await sync_once(
            self.upstream.sessions,
            self.upstream.clock,
            self.link.settings,
            make_client=self.link.make_client,
        )


@pytest.fixture
async def a2a(
    upstream: Instance, downstream: Instance, link: Link, monkeypatch: pytest.MonkeyPatch
) -> A2aPairing:
    # B labels the upstream from its own settings, as in polling.
    monkeypatch.setattr(
        "labhq.api.federation.a2a.get_federation_settings",
        lambda: FederationSettings(upstream_name=UPSTREAM_LABEL),
    )
    invitation = await Invites(downstream.sessions, clock=downstream.clock).create(label="a")
    added = await Nodes(upstream.sessions, clock=upstream.clock).add(
        NODE_URL,
        invitation.key,
        project="lab",
        name=NODE_NAME,
        a2a_url=A2A_URL,
    )
    link.settings.node_keys[NODE_NAME] = SecretStr(invitation.key)
    pairing = A2aPairing(
        upstream, downstream, link, invitation.key, added.node.id, added.manager.id
    )
    link.transport = RecordingTransport(httpx.ASGITransport(app=pairing.app()))
    return pairing
