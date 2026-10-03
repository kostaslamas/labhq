"""The Discord step: three manual actions for the owner, everything else checked and automated."""

import ast
import asyncio
import inspect
import logging
import stat
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from labhq.chat.discord.adapter import BOT_PERMISSIONS
from labhq.db import create_engine, session_factory
from labhq.db.models import Project
from labhq.db.models.chat import ChatBinding, ChatBindingKind
from labhq.onboard import (
    OnboardContext,
    OnboardError,
    OnboardSettings,
    PlatformInfo,
    StepRegistry,
    default_steps,
    run_steps,
)
from labhq.onboard import steps as steps_module
from labhq.onboard.discord import (
    PORTAL,
    SETUP_KEY,
    DiscordStep,
    bot_page,
    invite_link,
    project_channel_key,
)
from labhq.settings import Settings
from tests.chat.fake_discord import API, BOT_TOKEN, GUILD_ID, OWNER_ID
from tests.onboard.conftest import onboard
from tests.onboard.fakes.discord import APPLICATION_ID, FakeOnboardingDiscord, FrozenClock

ACTION_HEADER = "One step for you:"
PROJECTS = ("Alpha", "Beta Site")


@pytest.fixture(autouse=True)
def discord_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BOT_TOKEN", "GUILD_ID", "OWNER_ID"):
        monkeypatch.delenv(f"LABHQ_DISCORD_{name}", raising=False)
    monkeypatch.setenv("LABHQ_DISCORD_API_BASE", API)


@pytest.fixture
def discord() -> FakeOnboardingDiscord:
    return FakeOnboardingDiscord()


async def _add_projects(url: str) -> None:
    engine = create_engine(url)
    now = datetime(2026, 10, 3, tzinfo=UTC)
    async with session_factory(engine)() as db, db.begin():
        for name in PROJECTS:
            db.add(Project(name=name, repo_path=f"/repos/{name}", created_at=now, updated_at=now))
    await engine.dispose()


async def _bindings(url: str) -> list[tuple[ChatBindingKind, str]]:
    engine = create_engine(url)
    async with session_factory(engine)() as db:
        rows = await db.execute(select(ChatBinding.kind, ChatBinding.local_key))
        found = [(row.kind, row.local_key) for row in rows]
    await engine.dispose()
    return found


def make_context(
    data_dir: Path,
    database_url: str,
    discord: FakeOnboardingDiscord,
    lines: list[str],
    *,
    interactive: bool = True,
    offered: bool = True,
) -> OnboardContext:
    return OnboardContext(
        settings=Settings(data_dir=data_dir, database_url=database_url),
        onboard=OnboardSettings(),
        clock=FrozenClock(datetime(2026, 10, 3, tzinfo=UTC)),
        platform=PlatformInfo("linux", "x86_64"),
        environ={},
        which=lambda name: None,
        say=discord.answer_prompts(lines),
        confirm=(lambda prompt: discord.owner_acts()) if interactive else None,
        offered=frozenset({"discord"}) if offered else frozenset(),
    )


def run(
    context: OnboardContext, discord: FakeOnboardingDiscord, answers: list[str] | None = None
) -> list[str]:
    """Run the step alone; returns the summary of its verified outcome."""
    replies = list(answers if answers is not None else [BOT_TOKEN])
    step = DiscordStep(
        ask=lambda prompt, secret: replies.pop(0),
        transport=httpx.MockTransport(discord),
        connect=discord.connect,
    )
    registry = StepRegistry()
    registry.register(step, order=1)
    return [report.outcome.summary for report in run_steps(registry, context) if report.outcome]


def test_the_owner_does_three_things_and_labhq_the_rest(
    data_dir: Path, database_url: str, discord: FakeOnboardingDiscord
) -> None:
    asyncio.run(_add_projects(database_url))
    lines: list[str] = []

    summaries = run(make_context(data_dir, database_url, discord, lines), discord)

    assert sum(ACTION_HEADER in line for line in lines) == 3
    shown = [line.strip() for line in lines]
    assert [PORTAL, bot_page(APPLICATION_ID), invite_link(APPLICATION_ID)] == [
        link for link in shown if link.startswith("https://")
    ]
    assert summaries == [
        f"server {GUILD_ID}, 2 project channel(s); your reply as Kostas reached labhq"
    ]
    stored = data_dir / "discord"
    assert (stored / "guild_id").read_text() == GUILD_ID
    assert (stored / "owner_id").read_text() == OWNER_ID
    # One persona post in the check thread, under the persona's name rather than the bot's.
    [post] = discord.messages[discord.threads[-1]]
    assert post["username"] == "labhq setup"


def test_category_project_channels_and_webhooks_are_bound(
    data_dir: Path, database_url: str, discord: FakeOnboardingDiscord
) -> None:
    asyncio.run(_add_projects(database_url))
    run(make_context(data_dir, database_url, discord, []), discord)

    bindings = set(asyncio.run(_bindings(database_url)))

    assert (ChatBindingKind.CATEGORY, "labhq") in bindings
    for project_id in (1, 2):
        key = project_channel_key(project_id)
        assert {(ChatBindingKind.CHANNEL, key), (ChatBindingKind.WEBHOOK, key)} <= bindings
    names = {channel["name"] for channel in discord.channels.values()}
    assert {"labhq", "alpha", "beta-site", SETUP_KEY} == names


def test_a_second_run_reuses_everything_and_asks_nothing(
    data_dir: Path, database_url: str, discord: FakeOnboardingDiscord
) -> None:
    asyncio.run(_add_projects(database_url))
    run(make_context(data_dir, database_url, discord, []), discord)
    created = discord.created
    lines: list[str] = []

    # Not asked for this time: the stored token alone offers the step, without prompts.
    again = make_context(data_dir, database_url, discord, lines, interactive=False, offered=False)
    summaries = run(again, discord, answers=[])

    assert summaries == [f"server {GUILD_ID}, 2 project channel(s)"]
    assert discord.created == created
    assert not any(ACTION_HEADER in line for line in lines)


def test_the_invite_link_carries_exactly_the_adapters_permissions_and_scope() -> None:
    query = parse_qs(urlsplit(invite_link(APPLICATION_ID)).query, strict_parsing=True)

    assert query == {
        "client_id": [APPLICATION_ID],
        "scope": ["bot"],
        "permissions": [str(BOT_PERMISSIONS)],
    }


@pytest.mark.parametrize(
    ("token", "intent_on", "guilds", "reason", "link"),
    [
        ("not-the-token", False, [], "Discord refused the bot token", PORTAL),
        (BOT_TOKEN, False, [], "Message Content intent is off", bot_page(APPLICATION_ID)),
        (BOT_TOKEN, True, [], "the bot is in no server yet", invite_link(APPLICATION_ID)),
    ],
    ids=["wrong token", "no message content intent", "not in a guild"],
)
def test_each_failure_names_one_step_to_fix_and_never_ready(
    data_dir: Path,
    database_url: str,
    discord: FakeOnboardingDiscord,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    intent_on: bool,
    guilds: list[str],
    reason: str,
    link: str,
) -> None:
    monkeypatch.setenv("LABHQ_DISCORD_BOT_TOKEN", token)
    discord.intent_on = intent_on
    discord.guilds = guilds
    lines: list[str] = []
    context = make_context(data_dir, database_url, discord, lines, interactive=False)

    with pytest.raises(OnboardError) as raised:
        run(context, discord, answers=[])

    assert raised.value.step == "discord"
    assert reason in raised.value.reason
    assert raised.value.reason.endswith(link)
    assert token not in str(raised.value)
    assert sum(ACTION_HEADER in line for line in lines) == 1
    assert not (data_dir / "discord" / "verified").exists()


def test_a_wrong_pasted_token_is_asked_again_then_stops(
    data_dir: Path, database_url: str, discord: FakeOnboardingDiscord
) -> None:
    lines: list[str] = []
    context = make_context(data_dir, database_url, discord, lines)

    with pytest.raises(OnboardError, match="Discord refused the bot token"):
        run(context, discord, answers=["not-the-token", ""])

    assert sum(ACTION_HEADER in line for line in lines) == 2
    assert not (data_dir / "discord" / "bot_token").exists()


@pytest.mark.posix_only("POSIX file permission bits")
def test_the_token_file_is_owner_only_and_the_token_is_never_shown(
    data_dir: Path,
    database_url: str,
    discord: FakeOnboardingDiscord,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    lines: list[str] = []

    run(make_context(data_dir, database_url, discord, lines), discord)

    directory = data_dir / "discord"
    token_file = directory / "bot_token"
    assert token_file.read_text() == BOT_TOKEN
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert BOT_TOKEN not in "\n".join(lines)
    assert BOT_TOKEN not in caplog.text
    others = [path for path in data_dir.rglob("*") if path.is_file() and path != token_file]
    assert all(BOT_TOKEN.encode() not in path.read_bytes() for path in others)


def test_the_owner_id_is_asked_once_when_no_message_arrives(
    data_dir: Path,
    database_url: str,
    discord: FakeOnboardingDiscord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LABHQ_ONBOARD_DISCORD_OWNER_WAIT_SECONDS", "0.05")
    lines: list[str] = []
    context = make_context(data_dir, database_url, discord, lines)
    context.say = lambda line: (
        lines.append(line)
        if f"#{SETUP_KEY}" in line and "write" in line
        else discord.answer_prompts(lines)(line)
    )

    run(context, discord, answers=[BOT_TOKEN, OWNER_ID])

    assert (data_dir / "discord" / "owner_id").read_text() == OWNER_ID


def test_without_a_request_or_a_token_the_step_stays_idle(
    data_dir: Path, database_url: str, discord: FakeOnboardingDiscord
) -> None:
    context = make_context(data_dir, database_url, discord, [], offered=False)

    assert run(context, discord, answers=[]) == ["skipped, not requested"]
    assert discord.requests == []
    assert not (data_dir / "discord").exists()


def test_the_step_is_one_registration_in_the_registry() -> None:
    registrations = [
        node
        for node in ast.walk(ast.parse(inspect.getsource(steps_module)))
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "default_steps.register"
    ]
    discord = [call for call in registrations if "DiscordStep" in ast.unparse(call)]

    assert len(discord) == 1
    assert "discord" in default_steps
    assert isinstance(next(s for s in default_steps if s.name == "discord"), DiscordStep)


def test_an_unknown_optional_step_is_refused() -> None:
    result = onboard("slack-bot")

    assert result.exit_code == 1
    assert "no onboarding step named slack-bot" in result.output
