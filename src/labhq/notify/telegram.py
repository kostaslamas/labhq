"""Telegram Bot API `sendMessage`. The token sits in the request URL, so it is kept out of logs."""

import logging
import re

import httpx

from labhq.notify.base import Message, NotifyError

_BOT_TOKEN_IN_URL = re.compile(r"/bot[^/\s'\"]+/")
_REDACTED = "/bot<redacted>/"


class _RedactBotToken(logging.Filter):
    """httpx logs every request URL at INFO; rewrite the token out of the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _BOT_TOKEN_IN_URL.search(message):
            record.msg = _BOT_TOKEN_IN_URL.sub(_REDACTED, message)
            record.args = None
        return True


_FILTER = _RedactBotToken()


def protect_logs() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)


class TelegramNotifier:
    def __init__(self, client: httpx.AsyncClient, *, token: str, chat_id: str) -> None:
        protect_logs()
        self._client = client
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    async def send(self, message: Message) -> None:
        text = f"{message.title}\n{message.body}"
        if message.click_url:
            text += f"\n{message.click_url}"
        try:
            response = await self._client.post(
                self._url, json={"chat_id": self._chat_id, "text": text}
            )
        except httpx.HTTPError as error:
            # str(error) can embed the URL, and with it the token.
            raise NotifyError(f"telegram request failed: {type(error).__name__}") from None
        if response.is_error:
            raise NotifyError(f"telegram answered HTTP {response.status_code}")
