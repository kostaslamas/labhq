# Manual check: agents talk in a Slack thread and the owner's reply comes back

CI proves the Slack adapter against a mocked Web API and Socket Mode events from fixtures
(`tests/chat/test_slack*.py`), with the same contract checks as Discord. Only a real Slack
workspace can prove that the app's scopes allow what the adapter asks, that posts show each
agent's name and avatar, and that the owner's reply arrives over Socket Mode. Tests never do
it (CONTRIBUTING.md §7).

## What it proves

- The bot creates a `#labhq-check` channel once.
- A thread opens in that channel under the root message **labhq manual check**, and posts
  appear in it as **Alice (PM)** and **Bob (worker)**, each with its own avatar.
- A 9000-character message arrives as three messages, in order, none cut inside a word.
- A reply you write in the thread is printed by the check; nothing else is.
- Running the check a second time reuses the same channel.

## Set up

Create the app and the two tokens as in [the Slack guide](../guide/slack.md). Then:

```sh
export LABHQ_SLACK_BOT_TOKEN='xoxb-…'
export LABHQ_SLACK_APP_TOKEN='xapp-…'
export LABHQ_SLACK_OWNER_ID='U…'
uv run labhq init
uv run python -m labhq.chat.slack_check
```

## Steps

1. The check prints `posted to channel C…, thread C…:…; long message in 3`. In Slack, open
   `#labhq-check` and the thread under **labhq manual check**.
2. Confirm the first two replies show **Alice (PM)** and **Bob (worker)** with different
   avatars and the `APP` badge, not the bot's own name.
3. Confirm the long message is three replies in order, each ending at a line break.
4. From a second account (or ask someone), reply in the thread. The check prints nothing.
5. Write in `#labhq-check` itself, outside the thread. The check prints nothing.
6. Reply `ship it` in the thread from your own account. The check prints
   `reply from U…: 'ship it'` and exits 0.
7. Run the check again. It opens a second thread in the **same** `#labhq-check`; Slack shows
   no `#labhq-check-1` or other new channel.
8. Search the terminal output and your `LABHQ_DATA_DIR` for the tokens:
   `grep -r -e "$LABHQ_SLACK_BOT_TOKEN" -e "$LABHQ_SLACK_APP_TOKEN" "$LABHQ_DATA_DIR"` finds
   nothing.

Keep `#labhq-check` for the next run. If you archive it, labhq's binding still points to it
and the next run stops with `is_archived`; unarchive it first.

## Record the result

| Date | labhq commit | Slack plan and client | Steps passed | Notes |
|---|---|---|---|---|
| | | | | |
