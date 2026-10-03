"""A Discord whose state the owner changes by doing the three manual actions, for onboarding."""

import asyncio
import re
from collections.abc import Callable
from typing import Any

import httpx

from labhq.chat.contract import Speaker
from labhq.chat.discord.gateway import Payload
from labhq.clock import FakeClock
from labhq.onboard.discord import SETUP_KEY
from tests.chat.fake_discord import (
    BOT_TOKEN,
    GUILD_ID,
    FakeDiscordApi,
    ScriptedConnection,
    ScriptedGateway,
)

APPLICATION_ID = "1290000000000000001"
MESSAGE_CONTENT_LIMITED = 1 << 19
# Answered only with the bot token; anything else is a 401, as on the real API.
_AUTHENTICATED = ("/users/@me", "/applications/@me", "/users/@me/guilds")


class FakeOnboardingDiscord(FakeDiscordApi):
    def __init__(self) -> None:
        super().__init__()
        self.intent_on = False
        self.guilds: list[str] = []
        self.threads: list[str] = []
        self.gateway = ScriptedGateway()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._routes[:0] = [
            ("GET", _route("/users/@me"), lambda _r: {"id": APPLICATION_ID, "bot": True}),
            ("GET", _route("/applications/@me"), self._application),
            ("GET", _route("/users/@me/guilds"), self._guilds),
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v10")
        if path in _AUTHENTICATED and request.headers["Authorization"] != f"Bot {BOT_TOKEN}":
            self.requests.append(request)
            return httpx.Response(401, json={"message": "401: Unauthorized", "code": 0})
        return super().__call__(request)

    async def connect(self, url: str) -> ScriptedConnection:
        # The step runs `automate` and `verify` in separate event loops, and a queue is bound
        # to the first loop that waits on it; each loop gets a fresh one with what is pending.
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop = loop
            stale, self.gateway.events = self.gateway.events, asyncio.Queue()
            while not stale.empty():
                self.gateway.events.put_nowait(stale.get_nowait())
        return await self.gateway.connect(url)

    def owner_acts(self) -> bool:
        """What the owner does when asked to confirm: the next manual action in order."""
        if not self.intent_on:
            self.intent_on = True
        elif not self.guilds:
            self.guilds.append(GUILD_ID)
        return True

    def owner_writes(self, channel_id: str, text: str) -> None:
        self.gateway.deliver(Speaker.OWNER, channel_id, text, sequence=30 + len(self.requests))

    def channel_id(self, name: str) -> str:
        return next(key for key, channel in self.channels.items() if channel["name"] == name)

    def answer_prompts(self, lines: list[str]) -> Callable[[str], None]:
        """A `say` that records lines and writes in Discord when labhq asks the owner to."""

        def say(line: str) -> None:
            lines.append(line)
            if f"write any message in #{SETUP_KEY}" in line:
                self.owner_writes(self.channel_id(SETUP_KEY), "hello")
            if "reply to the thread" in line:
                self.owner_writes(self.threads[-1], "looks good")

        return say

    def _application(self, request: httpx.Request) -> Payload:
        return {"id": APPLICATION_ID, "flags": MESSAGE_CONTENT_LIMITED if self.intent_on else 0}

    def _guilds(self, request: httpx.Request) -> Any:
        return [{"id": guild, "name": "Lab"} for guild in self.guilds]

    def _create_thread(self, request: httpx.Request, channel_id: str) -> Payload:
        thread = super()._create_thread(request, channel_id)
        self.threads.append(thread["id"])
        return thread


class FrozenClock(FakeClock):
    """Time that never passes: the gateway's heartbeat waits forever instead of spinning."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.get_running_loop().create_future()


def _route(path: str) -> re.Pattern[str]:
    return re.compile(re.escape(path))
