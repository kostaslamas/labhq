import pytest
from fastapi import FastAPI
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.hooks import HookRegistry, default_hooks
from labhq.api.routes import RouterRegistry, default_routers
from labhq.api.settings import ApiSettings
from labhq.live.broker import Broker, Change
from labhq.live.endpoint import attach, live_router
from labhq.live.feed import ChangeFeed
from labhq.live.registry import TopicRegistry
from labhq.live.settings import LiveSettings

from .conftest import OWNER_HEADER

AUTHORIZED = {OWNER_HEADER: "kostas"}


def live_app(
    broker: Broker,
    resolvers: ResolverRegistry,
    api_settings: ApiSettings,
    heartbeat_seconds: float = 60.0,
) -> FastAPI:
    hooks = HookRegistry()
    hooks.register("live", attach(broker, LiveSettings(heartbeat_seconds=heartbeat_seconds)))
    routers = RouterRegistry()
    routers.register(live_router, public=True)
    return create_app(routers=routers, hooks=hooks, resolvers=resolvers, settings=api_settings)


def test_the_default_app_mounts_the_socket_and_the_broker_hook() -> None:
    assert any(spec.router is live_router and spec.public for spec in default_routers)
    assert len(default_hooks) >= 1


def test_an_unauthenticated_connection_is_refused(
    broker: Broker, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    with (
        TestClient(live_app(broker, resolvers, api_settings)) as client,
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect("/api/live"),
    ):
        pass
    assert refused.value.code == 1008
    assert len(broker) == 0


def test_with_no_resolver_registered_nobody_connects(
    broker: Broker, api_settings: ApiSettings
) -> None:
    app = live_app(broker, ResolverRegistry(), api_settings)
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/live", headers=AUTHORIZED),
    ):
        pass


def test_the_owner_receives_invalidations_without_row_data(
    broker: Broker, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    with (
        TestClient(live_app(broker, resolvers, api_settings)) as client,
        client.websocket_connect("/api/live", headers=AUTHORIZED) as socket,
    ):
        client.portal.call(broker.publish, Change("approvals", "7|7"))
        message = socket.receive_json()
    assert message == {"type": "invalidate", "topic": "approvals", "watermark": "7|7"}


def test_an_idle_socket_gets_heartbeats(
    broker: Broker, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    app = live_app(broker, resolvers, api_settings, heartbeat_seconds=0.01)
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/live", headers=AUTHORIZED) as socket,
    ):
        assert socket.receive_json() == {"type": "heartbeat"}
        assert socket.receive_json() == {"type": "heartbeat"}


def test_shutdown_closes_open_sockets(
    broker: Broker, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    with (
        TestClient(live_app(broker, resolvers, api_settings)) as client,
        client.websocket_connect("/api/live", headers=AUTHORIZED) as socket,
    ):
        client.portal.call(broker.close_all)
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 1001


def test_a_closed_client_leaves_no_subscription(
    broker: Broker, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    with TestClient(live_app(broker, resolvers, api_settings)) as client:
        with client.websocket_connect("/api/live", headers=AUTHORIZED):
            assert len(broker) == 1
        # Leaving the block waits for the endpoint to return.
        assert len(broker) == 0


def test_a_new_topic_is_one_registration(
    broker: Broker,
    resolvers: ResolverRegistry,
    api_settings: ApiSettings,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    topics = TopicRegistry()
    # The whole change a later topic makes: one call. Broker and endpoint stay as they are.
    topics.register("deployments", lambda: select(literal("v1")))
    feed = ChangeFeed(sessions, broker, topics)
    with (
        TestClient(live_app(broker, resolvers, api_settings)) as client,
        client.websocket_connect("/api/live", headers=AUTHORIZED) as socket,
    ):
        assert client.portal.call(feed.poll) == 1
        message = socket.receive_json()
    assert message == {"type": "invalidate", "topic": "deployments", "watermark": "v1"}
