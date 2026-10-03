"""The desktop UI's API, and the single ASGI app `labhq serve` runs on one port.

`create_app` builds the API from the registries in `routes`, `hooks` and `deps`; a new area
or lifespan hook is a registration there, never an edit here. `create_server_app` puts the
API at `/api`, the MCP app at `/mcp` (its own auth untouched) and the built UI at `/`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import labhq
from labhq.api.deps import ResolverRegistry, current_owner, default_resolvers
from labhq.api.errors import ERROR_RESPONSES, install_error_handlers
from labhq.api.hooks import HookRegistry, LifespanHook, default_hooks, lifespan_of
from labhq.api.routes import RouterRegistry, default_routers
from labhq.api.settings import ApiSettings, get_api_settings
from labhq.cli.context import Context

API_PREFIX = "/api"
MCP_PATH = "/mcp"
TITLE = "labhq"


class LifespanError(RuntimeError):
    """A mounted app refused to start."""


def operation_id(route: APIRoute) -> str:
    # The endpoint's name is the operationId, so it is `<area>_<verb>` and never changes
    # with the path or method; the generated TypeScript client keys on it.
    return route.name


def create_app(
    context: Context | None = None,
    *,
    routers: RouterRegistry = default_routers,
    hooks: HookRegistry = default_hooks,
    resolvers: ResolverRegistry = default_resolvers,
    settings: ApiSettings | None = None,
    extra_hooks: tuple[LifespanHook, ...] = (),
) -> FastAPI:
    app = FastAPI(
        title=TITLE,
        version=labhq.__version__,
        lifespan=lifespan_of([*extra_hooks, *hooks]),
        generate_unique_id_function=operation_id,
        # The schema is printed by `python -m labhq.api.openapi`; nothing is served unsigned
        # except the health check.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.context = context
    app.state.resolvers = resolvers
    app.state.settings = settings or get_api_settings()
    install_error_handlers(app)
    for spec in routers:
        app.include_router(
            spec.router,
            prefix=API_PREFIX,
            dependencies=[] if spec.public else [Depends(current_owner)],
            responses=ERROR_RESPONSES,
        )
    return app


class SinglePageApp(StaticFiles):
    """The built UI: a file when one matches, else `index.html` for the client router."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            # A missing asset or API path stays a 404; only page routes fall back.
            if error.status_code != 404 or Path(path).suffix or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)


def asgi_lifespan(app: ASGIApp) -> LifespanHook:
    """Drive another ASGI app's lifespan from ours, so its startup runs with the API's."""

    @asynccontextmanager
    async def hook(_: FastAPI) -> AsyncIterator[None]:
        inbox: asyncio.Queue[Message] = asyncio.Queue()
        outbox: asyncio.Queue[Message] = asyncio.Queue()
        scope: dict[str, Any] = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}

        async def run() -> None:
            await app(scope, inbox.get, outbox.put)

        task = asyncio.create_task(run())

        async def step(event: str) -> None:
            await inbox.put({"type": f"lifespan.{event}"})
            answer = asyncio.create_task(outbox.get())
            # An app that crashes instead of answering must not leave us waiting forever.
            await asyncio.wait({answer, task}, return_when=asyncio.FIRST_COMPLETED)
            if not answer.done():
                answer.cancel()
                task.result()
                raise LifespanError(f"the mounted app ended during lifespan {event}")
            reply = answer.result()
            if reply["type"] != f"lifespan.{event}.complete":
                raise LifespanError(reply.get("message") or f"lifespan {event} failed")

        await step("startup")
        try:
            yield
        finally:
            await step("shutdown")
            await task

    return hook


class PathDispatcher:
    """`/mcp` and everything under it goes to the MCP app exactly as before; the rest to the API.

    Pure ASGI rather than a Starlette `Mount`, so the MCP app and its bearer and secret-path
    guard see the same scope they saw when they were the whole server.
    """

    def __init__(self, api: ASGIApp, mcp: ASGIApp) -> None:
        self.api = api
        self.mcp = mcp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "lifespan" and (path == MCP_PATH or path.startswith(MCP_PATH + "/")):
            await self.mcp(scope, receive, send)
            return
        await self.api(scope, receive, send)


def create_server_app(
    context: Context | None,
    mcp: ASGIApp,
    *,
    settings: ApiSettings | None = None,
    **registries: Any,
) -> ASGIApp:
    settings = settings or get_api_settings()
    api = create_app(context, settings=settings, extra_hooks=(asgi_lifespan(mcp),), **registries)
    if settings.ui_dir.is_dir():
        api.mount("/", SinglePageApp(directory=settings.ui_dir, html=True), name="ui")
    return PathDispatcher(api, mcp)
