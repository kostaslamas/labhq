"""Pure-ASGI bearer-token guard with a secret-path fallback, and the token's storage."""

import hmac
import json
import os
import secrets
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

MCP_PATH = "/mcp"
SECRET_PATH_PREFIX = "/mcp/"
TOKEN_FILENAME = "mcp-token"


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
                    (b"www-authenticate", b'Bearer realm="labhq"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def token_path(data_dir: Path) -> Path:
    return data_dir / TOKEN_FILENAME


def load_token(data_dir: Path) -> str | None:
    path = token_path(data_dir)
    return path.read_text().strip() if path.exists() else None


def write_token(data_dir: Path) -> str:
    """Generate a token and store it with mode 0600; replaces any earlier one."""
    path = token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # Created 0600 from the start, so the secret is never readable by others, even briefly.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(token)
    path.chmod(0o600)
    return token


def ensure_token(data_dir: Path) -> str:
    return load_token(data_dir) or write_token(data_dir)
