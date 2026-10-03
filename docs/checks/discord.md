# Manual check: agents talk in a Discord thread and the owner's reply comes back

CI proves the Discord adapter against a mocked REST API and gateway events from fixtures
(`tests/chat/`). Only a real Discord server can prove that the bot is allowed to do what the
adapter asks, that webhook posts show each agent's name and avatar, and that the owner's
reply arrives over the gateway. Tests never do it (CONTRIBUTING.md §7).

## What it proves

- The bot creates a `labhq` category and a `#labhq-check` channel once, with one webhook.
- A public thread opens in that channel, and posts appear in it as **Alice (PM)** and
  **Bob (worker)**, each with its own avatar, not as the bot.
- A 4500-character message arrives as three messages, in order, none cut inside a word.
- A reply you write in the thread is printed by the check; nothing else is.
- Running the check a second time reuses the same channel (no `#labhq-check-1`).

## Set up the bot (once)

1. Open <https://discord.com/developers/applications>, choose **New Application**, name it
   `labhq`.
2. **Bot** page: **Reset Token**, copy the token. It is a credential: keep it in your shell
   or a secrets manager, never in a file in the repository.
3. **Bot** page, **Privileged Gateway Intents**: turn on **Message Content Intent** and save.
   Without it the gateway closes with code 4014 and the check says so.
4. Copy the **Application ID** from **General Information**, then open this invite link with
   it, pick your server and authorise:

   ```text
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot&permissions=34896610320
   ```

   `34896610320` is exactly the permissions the adapter uses
   (`labhq.chat.discord.adapter.BOT_PERMISSIONS`): View Channels, Manage Channels (the
   category and project channels), Manage Webhooks (one per channel) and Create Public
   Threads (one per meeting). Posts go through webhooks, so the bot needs no Send Messages.
5. In Discord, **User Settings > Advanced**, turn on **Developer Mode**. Right-click your
   server and **Copy Server ID**; right-click your own name and **Copy User ID**.

## Run it

```sh
export LABHQ_DISCORD_BOT_TOKEN='<the bot token>'
export LABHQ_DISCORD_GUILD_ID='<server id>'
export LABHQ_DISCORD_OWNER_ID='<your user id>'
uv run labhq init
uv run python -m labhq.chat.discord.check
```

1. The check prints `posted to #labhq-check, thread …; long message in 3`. In Discord, open
   the `labhq` category, `#labhq-check`, and the thread **labhq manual check**.
2. Confirm the first two posts show **Alice (PM)** and **Bob (worker)** with different
   avatars and the `APP`/bot badge of a webhook, not the bot's own name.
3. Confirm the long message is three posts in order, each ending at a line break.
4. From a second account (or ask someone), write in the thread. The check prints nothing.
5. Write in `#labhq-check` itself, outside the thread. The check prints nothing.
6. Write `ship it` in the thread from your own account. The check prints
   `reply from <you>: 'ship it'` and exits 0.
7. Run the check again. It opens a second thread in the **same** `#labhq-check`; the server
   shows no new channel, category or webhook (**Server Settings > Integrations > Webhooks**
   lists one `labhq` webhook for the channel).
8. Search the terminal output and `~/.local/share/labhq` (or your `LABHQ_DATA_DIR`) for the
   token: `grep -r "$LABHQ_DISCORD_BOT_TOKEN" "$LABHQ_DATA_DIR"` finds nothing.

Clean up by deleting the `#labhq-check` channel, or keep it for the next run.

## Record the result

| Date | labhq commit | Discord client | Steps passed | Notes |
|---|---|---|---|---|
| | | | | |
