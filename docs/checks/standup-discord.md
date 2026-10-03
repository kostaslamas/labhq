# Manual check: a standup mirrored live to a Discord thread

CI proves the bridge with fake agents and the fake chat adapter (`tests/meetings/channels/`):
a standup opens one thread in its project's channel and posts every transcript entry under
its agent's persona, then the minutes; an owner reply delivered twice is recorded once and
reaches the next turn; with the adapter down the meeting completes and the backlog is posted
in order once it is back; an opened incident is posted once to `#infra`. Only real agents on
a real Discord server prove that the thread reads like a meeting, with each agent writing
under its own name, so this is a manual check, run by the owner. Tests never do it
(CONTRIBUTING.md §7).

## What it proves

Plan §10, Phase 3 demo: a standup appears as a thread in the project's Discord channel, each
agent writing under its own name, and an owner reply in the thread reaches the transcript.

## Before you run it

- The Discord adapter check passes (`docs/checks/discord.md`), so the bot, its permissions
  and the Message Content intent are in place.
- A labhq data directory with a project whose manager and at least one lead are approved
  agents on the `claude` adapter, the pinned Claude Code binary on `PATH` (or
  `LABHQ_CLI_PATH`), and a Claude login or `ANTHROPIC_API_KEY` (ADR 0001).
- Optional: give an agent its own persona in `agents.config`, for example
  `{"persona": {"name": "Alice (PM)", "avatar_url": "https://…/alice.png"}}`. Without one the
  agent posts as `<title> (<role>)` with a generated avatar.

## Run it

In the first terminal, start the program, which runs the `chat` loop:

```sh
export LABHQ_DISCORD_BOT_TOKEN='<the bot token>'
export LABHQ_DISCORD_GUILD_ID='<server id>'
export LABHQ_DISCORD_OWNER_ID='<your user id>'
uv run labhq serve
```

In a second terminal, with the same variables, hold a standup:

```sh
uv run labhq meetings start <project> --kind standup
uv run labhq approvals approve <approval id from the line above>
uv run labhq meetings start --meeting <meeting id>
```

1. In Discord, open the `labhq` category and the channel named after the project. A thread
   **Standup M<id>, <date>** opens within a few seconds of the meeting starting; its first
   post is the agenda, from `labhq`.
2. Each turn appears in the thread as it is taken, under its agent's name (and avatar), not
   under the bot's name. Write down the names you see.
3. While the second participant has not spoken yet, write in the thread from your own
   account: `Prioritise the login bug.`
4. When the meeting ends, the minutes appear as the last post, from the facilitator: the
   decisions and the action items with their owners.
5. Run `uv run labhq meetings show <meeting id>`. The transcript lists your message once,
   under `Owner`, and the turns after it react to it. Your message is not posted to the
   thread a second time.
6. Optional, the outage: stop `labhq serve`, hold another standup, then start `labhq serve`
   again. The meeting completes while the program is down (`labhq meetings show` has the full
   transcript and minutes); once the program is back the thread fills in, in order.

## Record the result

| Date | labhq commit | Agents (names seen) | Steps passed | Notes |
|---|---|---|---|---|
| | | | | |
