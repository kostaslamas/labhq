"""Discord REST calls with rate-limit retries, keeping the bot and webhook tokens out of sight."""

import logging
import re
from typing import Any

import httpx

from labhq.chat.base import ChatError
from labhq.clock import Clock

# Webhook execution carries the webhook token in the path.
_WEBHOOK_TOKEN_IN_PATH = re.compile(r"(/webhooks/\d+/)[^/?\s'\"]+")
_DEFAULT_RETRY_AFTER = 1.0


def redact(text: str) -> str:
    return _WEBHOOK_TOKEN_IN_PATH.sub(r"\1<redacted>", text)


class _RedactWebhookToken(logging.Filter):
    """httpx logs every request URL at INFO; rewrite webhook tokens out of the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _WEBHOOK_TOKEN_IN_PATH.search(message):
            record.msg = redact(message)
            record.args = None
        return True


_FILTER = _RedactWebhookToken()


def protect_logs() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)


def retry_after(response: httpx.Response) -> float:
    """Seconds Discord asks us to wait: the JSON body is precise, the header is a fallback."""
    try:
        return float(response.json()["retry_after"])
    except (ValueError, KeyError, TypeError):
        pass
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return _DEFAULT_RETRY_AFTER


class DiscordRest:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        api_base: str,
        clock: Clock,
        max_attempts: int,
    ) -> None:
        protect_logs()
        self._client = client
        self._headers = {"Authorization": f"Bot {token}"}
        self._api_base = api_base.rstrip("/")
        self._clock = clock
        self._max_attempts = max_attempts

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        bot_auth: bool = True,
    ) -> Any:
        url = self._api_base + path
        # Webhook paths authenticate with their own token; the bot token is not sent there.
        headers = self._headers if bot_auth else {}
        for _ in range(self._max_attempts):
            try:
                response = await self._client.request(
                    method, url, json=json, params=params, headers=headers
                )
            except httpx.HTTPError as error:
                # str(error) can embed the URL, and with it a webhook token.
                raise ChatError(
                    f"discord {method} {redact(path)} failed: {type(error).__name__}"
                ) from None
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                await self._clock.sleep(retry_after(response))
                continue
            if response.is_error:
                raise ChatError(
                    f"discord {method} {redact(path)} answered HTTP {response.status_code}"
                )
            return response.json() if response.content else None
        raise ChatError(
            f"discord {method} {redact(path)} still rate limited after "
            f"{self._max_attempts} attempts"
        )
