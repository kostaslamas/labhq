"""A fake Ollama `/api/chat` on `httpx.MockTransport`: no network, no model.

It streams NDJSON chunks like Ollama does, records every request body, and knows a fixed
set of models. `hold` keeps the stream open after the first chunk until it is closed, which
is what an interrupt must do.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from labhq.adapters import AdapterFactory
from labhq.adapters.ollama import OllamaAdapter, OllamaSettings
from labhq.adapters.ollama_sessions import SessionStore

MODEL = "tiny:1b"


class HeldStream(httpx.AsyncByteStream):
    """Sends its chunks, then waits for a close that only the client can bring."""

    def __init__(self, chunks: list[bytes], server: "FakeOllama") -> None:
        self._chunks = chunks
        self._server = server

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        self._server.held.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self._server.closed_streams += 1


def _reply_ok(messages: list[dict[str, str]]) -> str:
    return "OK"


@dataclass
class FakeOllama:
    models: set[str] = field(default_factory=lambda: {MODEL})
    reply: Callable[[list[dict[str, str]]], str] = _reply_ok
    hold: bool = False
    refuse_connections: bool = False
    # Observations. `held` is set once a held stream has sent its chunks.
    held: asyncio.Event = field(default_factory=asyncio.Event)
    requests: list[dict[str, Any]] = field(default_factory=list)
    closed_streams: int = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def factory(self, store_dir: Path, **overrides: Any) -> AdapterFactory:
        settings = OllamaSettings(**{"base_url": "http://ollama.test", "model": MODEL, **overrides})

        def make() -> OllamaAdapter:
            return OllamaAdapter(
                transport=self.transport(), settings=settings, store=SessionStore(store_dir)
            )

        return make

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.refuse_connections:
            raise httpx.ConnectError("connection refused", request=request)
        body = json.loads(request.content)
        self.requests.append(body)
        if body["model"] not in self.models:
            error = f'model "{body["model"]}" not found, try pulling it first'
            return httpx.Response(404, json={"error": error})
        chunks = self._chunks(body)
        if self.hold:
            return httpx.Response(200, stream=HeldStream(chunks[:1], self))
        return httpx.Response(200, content=b"".join(chunks))

    def _chunks(self, body: dict[str, Any]) -> list[bytes]:
        words = self.reply(body["messages"]).split(" ")
        parts = [w if i == 0 else f" {w}" for i, w in enumerate(words)]
        lines: list[dict[str, Any]] = [
            {"model": body["model"], "message": {"role": "assistant", "content": p}, "done": False}
            for p in parts
        ]
        lines.append(
            {
                "model": body["model"],
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 11 * len(body["messages"]),
                "eval_count": len(parts),
            }
        )
        return [json.dumps(line).encode() + b"\n" for line in lines]
