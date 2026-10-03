"""The manual Discord check (docs/checks/discord.md): `python -m labhq.chat.discord.check`.

It talks to the real Discord with the bot configured in `LABHQ_DISCORD_*`, so it is never
run by tests (CONTRIBUTING.md §7).
"""

import asyncio
import sys

import httpx

from labhq.chat import BindingStore, ChatError, Persona
from labhq.chat.contract import long_message
from labhq.chat.discord.adapter import DiscordAdapter
from labhq.chat.discord.settings import DiscordSettings
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory

CHECK_CHANNEL = "labhq-check"
PERSONAS = (
    Persona("Alice (PM)", "https://api.dicebear.com/9.x/initials/png?seed=Alice"),
    Persona("Bob (worker)", "https://api.dicebear.com/9.x/initials/png?seed=Bob"),
)


async def run_check() -> None:
    clock = SystemClock()
    engine = create_engine()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            adapter = DiscordAdapter(
                settings=DiscordSettings(),
                store=BindingStore(session_factory(engine), "discord", clock=clock),
                client=client,
                clock=clock,
            )
            channel = await adapter.ensure_channel(CHECK_CHANNEL, "labhq check")
            thread = await adapter.open_thread(channel, "labhq manual check")
            await adapter.post(thread, PERSONAS[0], "Good morning. This is the labhq check.")
            await adapter.post(thread, PERSONAS[1], "Morning. A long message follows.")
            parts = await adapter.post(thread, PERSONAS[0], long_message())
            print(f"posted to #{CHECK_CHANNEL}, thread {thread.id}; long message in {len(parts)}")
            print("now reply in that thread from the owner account...")
            reply = await anext(adapter.replies())
            print(f"reply from {reply.author}: {reply.text!r}")
            await adapter.close()
    finally:
        await engine.dispose()


def main() -> int:
    try:
        asyncio.run(run_check())
    except ChatError as error:
        print(f"check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
