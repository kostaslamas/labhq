"""Pure-ASGI bearer-token guard with a secret-path fallback."""

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

MCP_PATH = "/mcp"
SECRET_PATH_PREFIX = "/mcp/"


def _tokens_match(candidate: str, expected: str) -> bool:
    # Constant-time compare so response timing does not leak the token.
    return hmac.compare_digest(candidate.encode(), expected.encode())


class BearerAuthMiddleware:
    """Requires `Authorization: Bearer <token>`, or the token as the path suffix.

    Pure ASGI (not BaseHTTPMiddleware) so streaming bodies and the lifespan
    of the wrapped MCP app pass through untouched.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if path.startswith(SECRET_PATH_PREFIX):
            if not _tokens_match(path[len(SECRET_PATH_PREFIX) :], self.token):
                await self._unauthorized(send)
                return
            # Rewrite so the MCP app only ever sees its canonical path; the
            # token must not travel further into logging or error messages.
            scope = {**scope, "path": MCP_PATH, "raw_path": MCP_PATH.encode()}
        elif not self._header_ok(scope):
            await self._unauthorized(send)
            return

        await self.app(scope, receive, send)

    def _header_ok(self, scope: Scope) -> bool:
        for name, value in scope["headers"]:
            if name == b"authorization":
                scheme, _, credentials = value.decode("latin-1").partition(" ")
                return scheme.lower() == "bearer" and _tokens_match(credentials, self.token)
        return False

    @staticmethod
    async def _unauthorized(send: Send) -> None:
        body = json.dumps({"error": "unauthorized"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="labhq-spike"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
