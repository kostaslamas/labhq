"""Step: the Discord bot. The owner does three things; labhq checks and does everything else.

The owner pastes the bot token, turns on the Message Content intent and opens the invite link.
labhq checks each against the Discord API, stores what it learns where `DiscordSettings` reads
it, creates the channels and webhooks through the adapter and proves the mirror end to end.
The token is read hidden, stored owner-only, and never printed, logged or put in an error.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import typer
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import BindingStore, Channel, ChatError, Persona, Reply
from labhq.chat.discord import DiscordAdapter, DiscordSettings
from labhq.chat.discord.adapter import BOT_PERMISSIONS
from labhq.chat.discord.gateway import Gateway, GatewayConnector, websocket_connect
from labhq.chat.discord.rest import DiscordRest
from labhq.chat.discord.settings import config_dir
from labhq.db import create_engine, session_factory
from labhq.db.models import Project
from labhq.db.models.chat import ChatBindingKind
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError
from labhq.onboard.runner import describe

ADAPTER = "discord"
PORTAL = "https://discord.com/developers/applications"
AUTHORIZE = "https://discord.com/oauth2/authorize"
# The OAuth2 scopes the adapter needs: it acts as a bot and nothing else.
SCOPES = ("bot",)
# Application flags: the intent is on, or on for a bot in fewer than 100 servers.
MESSAGE_CONTENT_FLAGS = (1 << 18) | (1 << 19)
SETUP_KEY = "labhq-setup"
SETUP_NAME = "labhq setup"
CHECK_PERSONA = Persona("labhq setup")
CHECK_THREAD = "labhq setup check"
VERIFIED_FILENAME = "verified"
# Discord ids are never 0, so an adapter built with it reads no replies; it only creates.
UNKNOWN_OWNER = "0"
INTERACTIVE = "run `labhq onboard discord` interactively"


class DiscordOnboardSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_ONBOARD_DISCORD_", extra="ignore")

    owner_wait_seconds: float = Field(default=300.0, gt=0)
    reply_wait_seconds: float = Field(default=300.0, gt=0)


class Stage(StrEnum):
    TOKEN = "token"
    INTENT = "intent"
    INVITE = "invite"
    READY = "ready"


@dataclass(frozen=True)
class Probe:
    stage: Stage
    reason: str
    application_id: str = ""
    guilds: tuple[str, ...] = ()


def bot_page(application_id: str) -> str:
    return f"{PORTAL}/{application_id}/bot"


def invite_link(application_id: str) -> str:
    scope = " ".join(SCOPES)
    query = {"client_id": application_id, "scope": scope, "permissions": str(BOT_PERMISSIONS)}
    return f"{AUTHORIZE}?{urlencode(query)}"


# The three things only the owner can do, one per stage that is not ready yet.
ACTIONS: dict[Stage, Callable[[Probe], ManualAction]] = {
    Stage.TOKEN: lambda probe: ManualAction(
        "In the Discord Developer Portal choose New Application, name it labhq, then on its "
        "Bot page press Reset Token and paste the token here.",
        link=PORTAL,
    ),
    Stage.INTENT: lambda probe: ManualAction(
        "On the bot's page, under Privileged Gateway Intents, turn on Message Content Intent "
        "and save.",
        link=bot_page(probe.application_id),
    ),
    Stage.INVITE: lambda probe: ManualAction(
        "Open the invite link, pick your server and authorise.",
        link=invite_link(probe.application_id),
    ),
}


def project_channel_key(project_id: int) -> str:
    """The `chat_bindings` key of a project's channel; the meeting mirror uses the same one."""
    return f"project:{project_id}"


def store(directory: Path, name: str, value: str) -> None:
    """Write one field as `DiscordSettings` reads it, created owner-only from the start."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(value)
    path.chmod(0o600)


def _prompt(text: str, secret: bool) -> str:
    answer: str = typer.prompt(text, default="", show_default=False, hide_input=secret)
    return answer.strip()


@dataclass
class _Api:
    """The few reads that tell which stage the bot is at. A refused token reads as None."""

    client: httpx.AsyncClient
    base: str
    token: str | None

    async def get(self, path: str) -> Any:
        try:
            response = await self.client.get(
                self.base.rstrip("/") + path, headers={"Authorization": f"Bot {self.token}"}
            )
        except httpx.HTTPError as error:
            # The error text may quote the request; only its kind is safe to show.
            raise StepError(f"cannot reach Discord ({type(error).__name__})") from None
        if response.status_code == httpx.codes.UNAUTHORIZED:
            return None
        if response.is_error:
            raise StepError(f"Discord answered HTTP {response.status_code} to GET {path}")
        return response.json()

    async def probe(self) -> Probe:
        if not self.token:
            return Probe(Stage.TOKEN, "no bot token yet")
        if await self.get("/users/@me") is None:
            return Probe(Stage.TOKEN, "Discord refused the bot token")
        application = await self.get("/applications/@me")
        application_id = str(application["id"])
        if not int(application.get("flags") or 0) & MESSAGE_CONTENT_FLAGS:
            return Probe(Stage.INTENT, "the Message Content intent is off", application_id)
        guilds = tuple(str(guild["id"]) for guild in await self.get("/users/@me/guilds"))
        if not guilds:
            return Probe(Stage.INVITE, "the bot is in no server yet", application_id)
        return Probe(Stage.READY, "the bot is ready", application_id, guilds)


class DiscordStep:
    name = "discord"
    # Required once offered: a Discord set up halfway must never let onboarding say ready.
    required = True

    def __init__(
        self,
        *,
        ask: Callable[[str, bool], str] = _prompt,
        transport: httpx.AsyncBaseTransport | None = None,
        connect: GatewayConnector = websocket_connect,
    ) -> None:
        self._ask = ask
        self._transport = transport
        self._connect = connect

    def detect(self, context: OnboardContext) -> Detection:
        if not self._offered(context):
            return Detection(True, "not set up; `labhq onboard discord` adds it")
        if self._verified(context):
            return Detection(True, "set up and checked before")
        return Detection(False, "not set up yet")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        # The owner's three actions depend on what the Discord API answers, so `automate`
        # asks for them in turn, each after checking the previous one.
        return None

    def automate(self, context: OnboardContext) -> None:
        if self._offered(context):
            asyncio.run(self._setup(context))

    def verify(self, context: OnboardContext) -> Outcome:
        if not self._offered(context):
            return Outcome("skipped, not requested")
        return asyncio.run(self._check(context))

    def _offered(self, context: OnboardContext) -> bool:
        return self.name in context.offered or DiscordSettings().bot_token is not None

    def _verified(self, context: OnboardContext) -> bool:
        return (config_dir(context.settings.data_dir) / VERIFIED_FILENAME).exists()

    @asynccontextmanager
    async def _open(self, context: OnboardContext) -> AsyncIterator["_Run"]:
        engine = create_engine(context.settings.resolved_database_url)
        timeout = context.onboard.http_timeout_seconds
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                yield _Run(
                    context, DiscordSettings(), session_factory(engine), client, self._connect
                )
        finally:
            await engine.dispose()

    async def _setup(self, context: OnboardContext) -> None:
        directory = config_dir(context.settings.data_dir)
        async with self._open(context) as run:
            settings = run.settings
            configured = settings.bot_token.get_secret_value() if settings.bot_token else None
            api = _Api(run.client, settings.api_base, configured)
            probe = await self._until_ready(context, api)
            token = api.token
            assert token is not None
            if token != configured:
                store(directory, "bot_token", token)
            guild = self._pick_guild(settings, probe.guilds)
            if guild != settings.guild_id:
                store(directory, "guild_id", guild)
            run.settings = settings.model_copy(
                update={"bot_token": SecretStr(token), "guild_id": guild}
            )
            await self._create(run)

    async def _until_ready(self, context: OnboardContext, api: _Api) -> Probe:
        # Discord applies each action as soon as it is saved, so a pending stage is not done.
        while (probe := await api.probe()).stage is not Stage.READY:
            action = ACTIONS[probe.stage](probe)
            context.say(f"{self.name}: {probe.reason}. One step for you:")
            for line in describe(action):
                context.say(f"  {line}")
            fix = StepError(f"{probe.reason}. {action.instruction} {action.link}")
            if context.confirm is None:
                raise fix
            if probe.stage is Stage.TOKEN:
                api.token = self._ask("Bot token (hidden; empty to stop)", True) or None
                if api.token is None:
                    raise fix
                continue
            if not context.confirm(f"Done with {self.name}?"):
                raise fix
        return probe

    @staticmethod
    def _pick_guild(settings: DiscordSettings, guilds: tuple[str, ...]) -> str:
        if settings.guild_id in guilds:
            return settings.guild_id
        if len(guilds) == 1:
            return guilds[0]
        raise StepError(
            f"the bot is in {len(guilds)} servers; remove it from the others, or set "
            "LABHQ_DISCORD_GUILD_ID to the server labhq should use"
        )

    async def _create(self, run: "_Run") -> None:
        """The setup channel, then the owner's id, then a channel and webhook per project."""
        owner = run.settings.owner_id
        creator = run.adapter(owner or UNKNOWN_OWNER)
        try:
            setup = await creator.ensure_channel(SETUP_KEY, SETUP_NAME)
            if owner is None:
                owner = await self._find_owner(run, setup)
                store(config_dir(run.context.settings.data_dir), "owner_id", owner)
            for project_id, name in await _projects(run.sessions):
                await creator.ensure_channel(project_channel_key(project_id), name)
        except ChatError as error:
            raise StepError(str(error)) from None
        finally:
            await creator.close()

    async def _find_owner(self, run: "_Run", setup: Channel) -> str:
        """Your user id, from your first message in the setup channel, or asked for once."""
        if run.context.confirm is None:
            raise StepError(f"{INTERACTIVE} to learn your user id, or set LABHQ_DISCORD_OWNER_ID")
        # Listening starts before the prompt, so a quick message is not missed.
        listening = asyncio.ensure_future(run.first_author(setup))
        run.context.say(f"{self.name}: write any message in #{SETUP_KEY} so labhq knows you.")
        try:
            return await asyncio.wait_for(listening, DiscordOnboardSettings().owner_wait_seconds)
        except TimeoutError:
            pass
        answer = self._ask("Your Discord user id (Developer Mode, then Copy User ID)", False)
        if not answer.isdigit():
            raise StepError("no Discord user id given; set LABHQ_DISCORD_OWNER_ID and run again")
        return answer

    async def _check(self, context: OnboardContext) -> Outcome:
        async with self._open(context) as run:
            settings = run.settings
            if not (settings.bot_token and settings.guild_id and settings.owner_id):
                raise StepError("the bot token, server or owner id is missing; run it again")
            bindings = BindingStore(run.sessions, ADAPTER, clock=context.clock)
            projects = await _projects(run.sessions)
            for project_id, name in projects:
                for kind in (ChatBindingKind.CHANNEL, ChatBindingKind.WEBHOOK):
                    if await bindings.external_id(kind, project_channel_key(project_id)) is None:
                        raise StepError(f"project {name!r} has no Discord {kind} yet")
            summary = f"server {settings.guild_id}, {len(projects)} project channel(s)"
            if self._verified(context) and self.name not in context.offered:
                return Outcome(summary)
            author = await self._round_trip(run, settings.owner_id)
        stamp = context.clock.now().isoformat()
        store(config_dir(context.settings.data_dir), VERIFIED_FILENAME, stamp)
        return Outcome(f"{summary}; your reply as {author} reached labhq")

    async def _round_trip(self, run: "_Run", owner: str) -> str:
        """One persona post in a new thread, and the owner's reply seen by the adapter."""
        if run.context.confirm is None:
            raise StepError(f"{INTERACTIVE}: the end-to-end check needs your reply in Discord")
        adapter = run.adapter(owner)
        listening: asyncio.Future[Reply] | None = None
        try:
            channel = await adapter.ensure_channel(SETUP_KEY, SETUP_NAME)
            thread = await adapter.open_thread(channel, CHECK_THREAD)
            listening = asyncio.ensure_future(anext(adapter.replies()))
            await adapter.post(thread, CHECK_PERSONA, "labhq is connected. Reply here to finish.")
            run.context.say(f"{self.name}: reply to the thread '{CHECK_THREAD}' in #{SETUP_KEY}.")
            timeout = DiscordOnboardSettings().reply_wait_seconds
            try:
                reply = await asyncio.wait_for(listening, timeout)
            except (TimeoutError, StopAsyncIteration):
                raise StepError(f"no reply from you reached labhq within {timeout:g}s") from None
            return reply.author
        except ChatError as error:
            raise StepError(str(error)) from None
        finally:
            await adapter.close()
            if listening is not None and not listening.done():
                listening.cancel()


@dataclass
class _Run:
    """What one pass of the step shares: settings so far, the database and the HTTP client."""

    context: OnboardContext
    settings: DiscordSettings
    sessions: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    connect: GatewayConnector

    def adapter(self, owner: str) -> DiscordAdapter:
        return DiscordAdapter(
            settings=self.settings.model_copy(update={"owner_id": owner}),
            store=BindingStore(self.sessions, ADAPTER, clock=self.context.clock),
            client=self.client,
            clock=self.context.clock,
            connect=self.connect,
        )

    async def first_author(self, channel: Channel) -> str:
        """The id of whoever writes first in `channel`, bots and webhooks aside."""
        assert self.settings.bot_token is not None
        token = self.settings.bot_token.get_secret_value()
        clock = self.context.clock
        rest = DiscordRest(
            self.client, token=token, api_base=self.settings.api_base, clock=clock, max_attempts=1
        )

        async def locate() -> str:
            return str((await rest.call("GET", "/gateway/bot"))["url"])

        reconnect = self.settings.reconnect_seconds
        gateway = Gateway(
            token=token,
            locate=locate,
            connect=self.connect,
            clock=clock,
            reconnect_seconds=reconnect,
        )
        try:
            async for message in gateway.messages():
                author = message.get("author") or {}
                if message.get("webhook_id") or author.get("bot"):
                    continue
                if str(message.get("channel_id")) == channel.id and author.get("id"):
                    return str(author["id"])
            raise StepError("the Discord gateway closed before you wrote")
        finally:
            await gateway.close()


async def _projects(sessions: async_sessionmaker[AsyncSession]) -> list[tuple[int, str]]:
    async with sessions() as db:
        rows = await db.execute(select(Project.id, Project.name).order_by(Project.id))
        return [(row.id, row.name) for row in rows]
