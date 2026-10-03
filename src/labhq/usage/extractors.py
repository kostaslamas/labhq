"""Extractors: captured screen text in, the JSON of `labhq.usage.schema.Extraction` out.

An extractor is a registry entry. The default asks a model once, with no tools, through
the adapter registry: its run is an ordinary run of the configured extractor agent, so its
cost is recorded like any other. The worker never extracts its own usage (ADR 0003).
"""

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.db.enums import RunStatus
from labhq.db.models import RunEvent
from labhq.runs import RunService


class Extractor(Protocol):
    async def extract(self, captured: str, agent_kind: str) -> str:
        """Return the extractor's raw answer; `labhq.usage.schema` checks it."""
        ...


class ExtractorUnavailableError(RuntimeError):
    pass


PROMPT = """You read a terminal screen captured from the {agent_kind} coding agent and report
its usage. Answer with one JSON object and nothing else:

{{"readings": [{{"unit": "usd" | "percent" | "percent_left" | "tokens" | "requests",
                 "value": <number>, "window": <short name or null>,
                 "limit": <number or null>, "resets_at": <ISO 8601 UTC instant or null>}}],
  "limit_notice": <true if the screen says a usage or plan limit is reached>,
  "limit_resets_at": <ISO 8601 UTC instant when that limit resets, or null>}}

Copy every number exactly as the screen shows it; never compute, round or convert one.
A percentage the screen calls used is "percent"; one it calls left or remaining is
"percent_left".
Report only what the screen shows. If it shows no usage, return an empty "readings" list.
The screen was captured at {captured_at}.

<screen>
{captured}
</screen>
"""


class ModelExtractor:
    """One run of `agent_id` per extraction. Configure that agent with `tools: []`."""

    def __init__(
        self,
        runs: RunService,
        sessions: async_sessionmaker[AsyncSession],
        agent_id: int | None,
        captured_at: Callable[[], str],
    ) -> None:
        self._runs = runs
        self._sessions = sessions
        self._agent_id = agent_id
        self._captured_at = captured_at

    async def extract(self, captured: str, agent_kind: str) -> str:
        if self._agent_id is None:
            raise ExtractorUnavailableError("no extractor agent is configured")
        prompt = PROMPT.format(
            agent_kind=agent_kind, captured=captured, captured_at=self._captured_at()
        )
        run = await self._runs.execute(agent_id=self._agent_id, task_id=None, prompt=prompt)
        if run.status is not RunStatus.SUCCEEDED:
            raise ExtractorUnavailableError(f"extraction run {run.id} ended {run.status}")
        async with self._sessions() as db:
            payload = await db.scalar(
                select(RunEvent.payload)
                .where(RunEvent.run_id == run.id, RunEvent.kind == "result")
                .order_by(RunEvent.seq.desc())
                .limit(1)
            )
        answer = payload.get("result") if payload else None
        if not isinstance(answer, str):
            raise ExtractorUnavailableError(f"extraction run {run.id} returned no text")
        return answer


class UnknownExtractorError(LookupError):
    pass


class ExtractorRegistry:
    def __init__(self) -> None:
        self._extractors: dict[str, Extractor] = {}

    def register(self, key: str, extractor: Extractor, *, replace: bool = False) -> None:
        if key in self._extractors and not replace:
            raise ValueError(f"extractor {key!r} is already registered")
        self._extractors[key] = extractor

    def get(self, key: str) -> Extractor:
        try:
            return self._extractors[key]
        except KeyError:
            raise UnknownExtractorError(f"no extractor registered as {key!r}") from None
