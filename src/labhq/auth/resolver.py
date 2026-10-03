"""The session resolver behind `current_owner`, and the cookie it reads.

A request is the owner when it carries a live session cookie. A write also has to carry the
custom header, which a cross-site form or image cannot set; with SameSite=Strict that is the
CSRF defence.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response

from labhq.api.deps import Owner, ResolverRegistry, default_resolvers
from labhq.api.errors import ApiError
from labhq.auth.sessions import find_session
from labhq.auth.settings import AuthSettings, get_auth_settings

WRITE_HEADER = "X-Labhq-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RESOLVER_NAME = "web-session"


@dataclass(frozen=True)
class SessionOwner(Owner):
    """The owner as a signed-in browser: the session is what a step-up binds its challenge to."""

    session_id: int


def is_loopback(request: Request) -> bool:
    return request.url.hostname in LOOPBACK_HOSTS


def set_session_cookie(
    request: Request, response: Response, settings: AuthSettings, token: str
) -> None:
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_absolute_seconds,
        httponly=True,
        samesite="strict",
        # Secure everywhere a browser would accept it; plain loopback is the one exception.
        secure=not is_loopback(request),
        path="/",
    )


def clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


async def resolve_session(request: Request) -> Owner | None:
    settings = get_auth_settings()
    token = request.cookies.get(settings.session_cookie)
    context: Any = getattr(request.app.state, "context", None)
    if not token or context is None:
        return None
    async with context.sessions() as db:
        session = await find_session(db, settings, context.clock.now(), token)
        if session is None:
            return None
        session_id = session.id
        await db.commit()
    # A WebSocket handshake is a GET and has no `method` attribute.
    method = getattr(request, "method", "GET")
    if method.upper() not in SAFE_METHODS and request.headers.get(WRITE_HEADER) != "1":
        raise ApiError(403, "write_header_required", f"Writes need the {WRITE_HEADER}: 1 header.")
    return SessionOwner("owner", session_id)


def register(resolvers: ResolverRegistry = default_resolvers) -> None:
    resolvers.register(RESOLVER_NAME, resolve_session)
