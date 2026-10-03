"""The Ollama adapter: a local model behind the adapter contract, over `/api/chat`.

It serves roles that read and write text; it offers the model no tools. A coding worker on
a local model runs through a CLI that supports Ollama instead. Ollama keeps no session, so
the conversation lives in `ollama_sessions` under the data directory.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, RunRequest
from labhq.adapters.ollama_sessions import (
    Message,
    SessionStore,
    StoredSession,
    new_session_id,
)
from labhq.settings import get_settings

CHAT_PATH = "/api/chat"
SESSIONS_DIRNAME = "ollama-sessions"
# The values the SDK reports, so `labhq.runs.status` maps them without a new entry.
INTERRUPTED_REASON = "aborted_streaming"
ERROR_SUBTYPE = "error_during_execution"
# Ollama's final chunk names tokens its own way; runs store them under the shared names.
USAGE_KEYS = {"prompt_eval_count": "input_tokens", "eval_count": "output_tokens"}


class OllamaSettings(BaseSettings):
    """Defaults for every Ollama agent, from `LABHQ_OLLAMA_*`; `agents.config` overrides."""

    model_config = SettingsConfigDict(env_prefix="LABHQ_OLLAMA_", extra="ignore")

    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2"
    connect_timeout_s: float = 5.0
    # A cold model loads before its first token arrives; a short read timeout fails that.
    read_timeout_s: float = 300.0


class OllamaAgentConfig(BaseModel):
    """The keys of `agents.config` this adapter reads; other keys belong to other modules."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    base_url: str | None = None
    model: str | None = None
    # The role's standing instructions, sent as the first message of a new conversation.
    system: str | None = None
    # Passed through as Ollama's `options`, for example temperature or num_ctx.
    options: dict[str, Any] | None = None


class OllamaError(Exception):
    """The run cannot go on; the message says what the user should do about it."""


class OllamaAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        settings: OllamaSettings | None = None,
        store: SessionStore | None = None,
    ) -> None:
        # Settings and the store resolve at start, so registering the class reads nothing.
        self._transport = transport
        self._settings = settings
        self._store = store
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[AdapterEvent | None] = asyncio.Queue()
        self._messages: list[Message] = []
        self._pending: list[str] = []
        self._partial: list[str] = []
        self._usage: dict[str, int] = {}
        self._turns = 0
        self._interrupted = False
        self._failure: str | None = None
        self._result: AdapterResult | None = None

    async def start(self, request: RunRequest) -> None:
        if self._task is not None:
            raise AdapterError("an adapter instance serves one run")
        settings = self._settings or OllamaSettings()
        config = OllamaAgentConfig.model_validate(dict(request.config))
        store = self._store or SessionStore(get_settings().data_dir / SESSIONS_DIRNAME)
        self._store = store
        self._base_url = config.base_url or settings.base_url
        self._model = config.model or settings.model
        self._options = config.options
        self._resumed = request.resume_session_id
        if request.resume_session_id is not None:
            self._session_id = request.resume_session_id
            self._messages = store.load(request.resume_session_id).messages
        else:
            self._session_id = new_session_id()
            if config.system:
                self._messages = [{"role": "system", "content": config.system}]
        self._messages.append({"role": "user", "content": request.prompt})
        timeout = httpx.Timeout(settings.read_timeout_s, connect=settings.connect_timeout_s)
        self._client = httpx.AsyncClient(
            base_url=self._base_url, transport=self._transport, timeout=timeout
        )
        self._task = asyncio.create_task(self._pump())

    async def events(self) -> AsyncIterator[AdapterEvent]:
        task = self._running()
        yield AdapterEvent(
            "system",
            {
                "subtype": "init",
                "model": self._model,
                "session_id": self._session_id,
                "resumed": self._resumed is not None,
            },
        )
        while (event := await self._queue.get()) is not None:
            yield event
        # The pump has put its last event; waiting here never raises, even when cancelled.
        await asyncio.wait([task])
        self._result = self._final_result()
        yield AdapterEvent(
            "result", {"subtype": self._result.subtype, "usage": dict(self._result.usage)}
        )

    async def send(self, text: str) -> None:
        # Ollama takes no input mid-stream: the text is the next user turn of this run.
        if self._running().done():
            raise AdapterError("the run has finished; start a new one to continue")
        self._pending.append(text)

    async def interrupt(self) -> None:
        task = self._running()
        if task.done():
            return
        self._interrupted = True
        # Cancelling leaves the `client.stream` block, which closes the response.
        task.cancel()

    def result(self) -> AdapterResult:
        if self._result is None:
            raise AdapterError("the run has no result yet")
        return self._result

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait([task])
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _running(self) -> asyncio.Task[None]:
        if self._task is None:
            raise AdapterError("start() was not called")
        return self._task

    async def _pump(self) -> None:
        try:
            await self._turn()
            while self._pending:
                self._messages.extend({"role": "user", "content": t} for t in self._pending)
                self._pending.clear()
                await self._turn()
        except OllamaError as error:
            self._failure = str(error)
        except httpx.ConnectError:
            self._failure = (
                f"cannot reach Ollama at {self._base_url}: start it with `ollama serve`, "
                "or set base_url in the agent's config"
            )
        except httpx.HTTPError as error:
            self._failure = f"the request to Ollama at {self._base_url} failed: {error!r}"
        finally:
            self._queue.put_nowait(None)

    async def _turn(self) -> None:
        assert self._client is not None
        body: dict[str, Any] = {"model": self._model, "messages": self._messages, "stream": True}
        if self._options:
            body["options"] = self._options
        self._partial = []
        final: dict[str, Any] | None = None
        async with self._client.stream("POST", CHAT_PATH, json=body) as response:
            if response.status_code != httpx.codes.OK:
                await response.aread()
                raise OllamaError(self._refusal(response))
            async for line in response.aiter_lines():
                chunk = _chunk(line)
                if chunk is None:
                    continue
                text = str(chunk.get("message", {}).get("content") or "")
                if text:
                    self._partial.append(text)
                    self._queue.put_nowait(AdapterEvent("assistant", {"text": text}))
                if chunk.get("done"):
                    final = chunk
                    break
        if final is None:
            raise OllamaError("Ollama closed the stream before the reply was done")
        self._messages.append({"role": "assistant", "content": "".join(self._partial)})
        self._partial = []
        self._turns += 1
        self._model = str(final.get("model") or self._model)
        for source, name in USAGE_KEYS.items():
            self._usage[name] = self._usage.get(name, 0) + int(final.get(source) or 0)

    def _refusal(self, response: httpx.Response) -> str:
        detail = _error_text(response)
        if response.status_code == httpx.codes.NOT_FOUND:
            return (
                f"Ollama at {self._base_url} has no model {self._model!r}: "
                f"pull it with `ollama pull {self._model}` ({detail})"
            )
        return f"Ollama at {self._base_url} answered {response.status_code}: {detail}"

    def _final_result(self) -> AdapterResult:
        if self._failure is not None:
            # Nothing new to keep: a resumed session stays as it was, a new one is dropped.
            return AdapterResult(
                subtype=ERROR_SUBTYPE,
                is_error=True,
                session_id=self._resumed,
                cost_usd=0.0,
                usage=dict(self._usage),
                model=self._model,
                num_turns=self._turns,
                errors=[self._failure],
            )
        if self._interrupted and self._partial:
            # What the model said before the interrupt is part of the conversation it resumes.
            self._messages.append({"role": "assistant", "content": "".join(self._partial)})
        assert self._store is not None
        self._store.save(self._session_id, StoredSession(self._model, self._messages))
        last = self._messages[-1]
        return AdapterResult(
            subtype=ERROR_SUBTYPE if self._interrupted else "success",
            is_error=self._interrupted,
            session_id=self._session_id,
            terminal_reason=INTERRUPTED_REASON if self._interrupted else "completed",
            # A local model costs nothing per token; runs record it as 0 micros (ADR 0002).
            cost_usd=0.0,
            usage=dict(self._usage),
            model=self._model,
            num_turns=self._turns,
            text=None if self._interrupted else last["content"],
        )


def _chunk(line: str) -> dict[str, Any] | None:
    if not line.strip():
        return None
    try:
        chunk: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        raise OllamaError(f"Ollama sent a line that is not JSON: {line[:200]!r}") from None
    if "error" in chunk:
        raise OllamaError(f"Ollama stopped with an error: {chunk['error']}")
    return chunk


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error") or response.text)
    except (json.JSONDecodeError, AttributeError):
        return response.text
