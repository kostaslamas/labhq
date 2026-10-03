"""The manual Slack check (docs/checks/slack-meetings.md): `python -m labhq.chat.slack_check`.

It talks to the real Slack with the app configured in `LABHQ_SLACK_*`, so it is never run
by tests (CONTRIBUTING.md §7).
"""

import asyncio
import sys

import httpx

from labhq.chat import BindingStore, ChatError, Persona
from labhq.chat.contract import long_message
from labhq.chat.slack import SlackAdapter
from labhq.chat.slack_settings import SlackSettings
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory

CHECK_KEY = "labhq-check"
PERSONAS = (
    Persona("Alice (PM)", "https://api.dicebear.com/9.x/initials/png?seed=Alice"),
    Persona("Bob (worker)", "https://api.dicebear.com/9.x/initials/png?seed=Bob"),
)


async def run_check() -> None:
    clock = SystemClock()
    engine = create_engine()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            adapter = SlackAdapter(
                settings=SlackSettings(),
                store=BindingStore(session_factory(engine), "slack", clock=clock),
                client=client,
                clock=clock,
            )
            channel = await adapter.ensure_channel(CHECK_KEY, "check")
            thread = await adapter.open_thread(channel, "labhq manual check")
            await adapter.post(thread, PERSONAS[0], "Good morning. This is the labhq check.")
            await adapter.post(thread, PERSONAS[1], "Morning. A long message follows.")
            text = long_message(adapter.max_message_length)
            parts = await adapter.post(thread, PERSONAS[0], text)
            print(
                f"posted to channel {channel.id}, thread {thread.id}; long message in {len(parts)}"
            )
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
