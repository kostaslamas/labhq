# Discord: meetings mirrored to your own server

labhq can mirror meetings into a Discord server you own: a `labhq` category, one channel per
project, a thread per meeting, and each agent posting under its own name and avatar. Your
replies in a meeting thread reach labhq. Discord is optional; without it meetings are read in
the UI and through the connector as before.

## Set it up

```sh
labhq onboard discord
```

This runs the usual onboarding and adds the Discord step. You do three things, each shown as
one step with a ready link; labhq checks each one against the Discord API before it moves on.

| # | What you do | Link labhq shows |
|---|---|---|
| 1 | Create an application, then on its **Bot** page press **Reset Token** and paste the token when asked (the input is hidden) | <https://discord.com/developers/applications> |
| 2 | Under **Privileged Gateway Intents**, turn on **Message Content Intent** and save | the **Bot** page of your application |
| 3 | Open the invite link, pick your server and authorise | an invite link with exactly the permissions the bot uses |

Everything else is automated:

- labhq validates the token, reads the application id from the API and builds the invite
  link from it. The link asks for the `bot` scope and four permissions: View Channels, Manage
  Channels, Manage Webhooks and Create Public Threads. Posts go through webhooks, so the bot
  needs no Send Messages.
- It waits until the bot has joined your server and records the server id.
- It creates `#labhq-setup` in the `labhq` category and asks you to write any message there;
  your user id is read from that message. If none arrives within five minutes it asks for the
  id once (Discord **Developer Mode**, then right-click your name, **Copy User ID**).
- It creates a channel and a webhook for every existing project.
- Before it says `labhq is ready.` it opens a thread **labhq setup check** in `#labhq-setup`,
  posts one message there as **labhq setup**, and waits for your reply in that thread.

If a check fails, onboarding names the one thing to fix (a refused token, the intent still
off, the bot in no server) and never says ready. Run `labhq onboard discord` again after
fixing it.

## Where the settings live

labhq stores what it learns in `<data dir>/discord/`, one file per setting: `bot_token`,
`guild_id` and `owner_id`. The directory is mode 0700 and each file 0600. The token is a
credential: labhq never prints it, logs it or puts it in an error message.

The same settings can come from variables instead, which win over the files:
`LABHQ_DISCORD_BOT_TOKEN`, `LABHQ_DISCORD_GUILD_ID` and `LABHQ_DISCORD_OWNER_ID`.

Once a token is stored, every later `labhq onboard` runs the Discord step without being
asked: it re-checks the bot and creates channels for projects added since, and asks you
nothing unless something broke. `labhq onboard discord` repeats the reply check too.

| Variable | Default | Effect |
|---|---|---|
| `LABHQ_ONBOARD_DISCORD_OWNER_WAIT_SECONDS` | 300 | How long to wait for your message in `#labhq-setup` |
| `LABHQ_ONBOARD_DISCORD_REPLY_WAIT_SECONDS` | 300 | How long to wait for your reply in the check thread |

## Removing it

Delete `<data dir>/discord/` and kick the bot from your server. The channels stay in Discord
until you delete them; labhq's own records of them are in the database's `chat_bindings`.
