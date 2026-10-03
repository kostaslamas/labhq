"""One authenticated `initialize` call through the public URL, before anything says ready."""

import time
from collections.abc import Callable

import httpx

from labhq.expose.base import ExposureError
from labhq.mcp.auth import SECRET_PATH_PREFIX

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "labhq-expose-check", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
# A fresh quick-tunnel hostname can take a few seconds to resolve after cloudflared prints it.
DEFAULT_ATTEMPTS = 6
DEFAULT_DELAY_SECONDS = 2.0


def connector_url(public_url: str, secret: str) -> str:
    return f"{public_url}{SECRET_PATH_PREFIX}{secret}"


def verify_connector(
    public_url: str,
    secret: str,
    *,
    client: httpx.Client | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Raises `ExposureError` unless the tunnel answers `initialize` with a JSON result.

    The error never contains the connector URL, because the URL holds the secret.
    """
    url = connector_url(public_url, secret)
    http = client or httpx.Client(timeout=10.0)
    reason = "no attempt was made"
    try:
        for attempt in range(attempts):
            if attempt:
                sleep(delay)
            try:
                response = http.post(url, json=INITIALIZE, headers=HEADERS)
            except httpx.HTTPError as error:
                reason = type(error).__name__
                continue
            if response.status_code == 200 and _is_initialize_result(response):
                return
            reason = f"HTTP {response.status_code}"
    finally:
        if client is None:
            http.close()
    raise ExposureError(f"the public URL did not answer `initialize` ({reason})")


def _is_initialize_result(response: httpx.Response) -> bool:
    if not response.headers.get("content-type", "").startswith("application/json"):
        return False
    try:
        return "result" in response.json()
    except ValueError:
        return False
