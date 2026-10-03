"""Slack Web API calls with rate-limit retries, keeping the tokens out of sight.

Slack answers most failures with HTTP 200 and `{"ok": false, "error": ...}`; only rate
limits use a status code (429 with `Retry-After`).
"""

from typing import Any

import httpx

from labhq.chat.base import ChatError
from labhq.clock import Clock

_DEFAULT_RETRY_AFTER = 1.0


class SlackApiError(ChatError):
    """The Web API answered `ok: false`. `error` is Slack's code, never a credential."""

    def __init__(self, method: str, error: str) -> None:
        super().__init__(f"slack {method} failed: {error}")
        self.error = error


def retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return _DEFAULT_RETRY_AFTER


class SlackApi:
    def __init__(
        self, client: httpx.AsyncClient, *, api_base: str, clock: Clock, max_attempts: int
    ) -> None:
        self._client = client
        self._api_base = api_base.rstrip("/")
        self._clock = clock
        self._max_attempts = max_attempts

    async def call(self, method: str, token: str, body: dict[str, Any] | None = None) -> Any:
        """POST `body` as JSON to the Web API `method`, authenticated with `token`."""
        url = f"{self._api_base}/{method}"
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(self._max_attempts):
            try:
                response = await self._client.post(url, json=body or {}, headers=headers)
            except httpx.HTTPError as error:
                # The request, and with it the Authorization header, hangs off the error.
                raise ChatError(f"slack {method} failed: {type(error).__name__}") from None
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                await self._clock.sleep(retry_after(response))
                continue
            if response.is_error:
                raise ChatError(f"slack {method} answered HTTP {response.status_code}")
            payload = response.json()
            if not payload.get("ok"):
                raise SlackApiError(method, str(payload.get("error", "unknown_error")))
            return payload
        raise ChatError(f"slack {method} still rate limited after {self._max_attempts} attempts")
