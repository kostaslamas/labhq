"""ntfy: POST the body to `<server>/<topic>`, with title, priority and click URL as headers."""

import base64

import httpx

from labhq.notify.base import Message, NotifyError


def _header(value: str) -> str:
    """HTTP headers are ASCII; ntfy reads RFC 2047 encoded words for anything else."""
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode() + "?="


class NtfyNotifier:
    def __init__(
        self, client: httpx.AsyncClient, *, server: str, topic: str, priority: str
    ) -> None:
        self._client = client
        self._url = f"{server.rstrip('/')}/{topic}"
        self._priority = priority

    async def send(self, message: Message) -> None:
        headers = {"Title": _header(message.title), "Priority": self._priority}
        if message.click_url:
            headers["Click"] = message.click_url
        try:
            response = await self._client.post(
                self._url, content=message.body.encode(), headers=headers
            )
        except httpx.HTTPError as error:
            raise NotifyError(f"ntfy request failed: {type(error).__name__}") from None
        if response.is_error:
            raise NotifyError(f"ntfy answered HTTP {response.status_code}")
