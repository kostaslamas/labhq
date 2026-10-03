# Manual check: a new owner reaches a working Discord mirror in three manual steps

CI proves the Discord onboarding step against a fake Discord API and gateway
(`tests/onboard/test_discord.py`): it counts the manual actions, checks the invite link
against the adapter's permissions, and checks each failure. Only a real Discord account and
server can prove that the links land on the right pages and that the bot really works with
what the owner did. Tests never do it (CONTRIBUTING.md §7).

## What it proves

- labhq asks for exactly three manual actions: create the application and paste the token,
  turn on Message Content, open the invite link.
- Each link opens the right page: the Developer Portal, the bot page of the new application,
  and an authorisation page that lists View Channels, Manage Channels, Manage Webhooks and
  Create Public Threads, and nothing else.
- After the step, the server has a `labhq` category with `#labhq-setup` and one channel per
  project, each with one `labhq` webhook.
- A persona post appears in a thread and your reply reaches labhq before it says ready.
- The token is stored owner-only and appears nowhere else.

## Before you start

- A Discord account and a server you own, with no labhq bot in it yet.
- A fresh data directory with two projects:

  ```sh
  export LABHQ_DATA_DIR="$(mktemp -d)"
  uv run labhq init
  git init -q /tmp/alpha && git init -q /tmp/beta
  uv run labhq project add alpha --repo /tmp/alpha
  uv run labhq project add beta --repo /tmp/beta
  ```
- `cloudflared` installed, since the rest of onboarding needs it.

## Run it

```sh
uv run labhq onboard discord --no-serve
```

Count the times labhq prints `discord: … One step for you:`. Do only what each one says.

1. **Token.** Open the first link, choose **New Application**, name it `labhq`, open **Bot**,
   **Reset Token**, copy it and paste it at the hidden prompt.
2. **Intent.** Open the second link. Confirm it is the **Bot** page of the application you
   just made. Turn on **Message Content Intent**, save, answer `y`.
3. **Invite.** Open the third link. Confirm the page lists exactly the four permissions above.
   Pick your server, authorise, answer `y`.
4. labhq asks you to write in `#labhq-setup`. Write anything there.
5. labhq asks you to reply to the thread **labhq setup check**. Confirm the thread holds one
   post from **labhq setup**, then reply in it.
6. The run ends with `discord: ok, server …, 2 project channel(s); your reply as … reached
   labhq` and then `labhq is ready.`

Then check:

7. In Discord, the `labhq` category holds `#labhq-setup`, `#alpha` and `#beta`, and
   **Server Settings > Integrations > Webhooks** lists one `labhq` webhook per channel.
8. `ls -l "$LABHQ_DATA_DIR/discord"` shows `bot_token` as `-rw-------`, and the directory is
   `drwx------`.
9. Copy the token from the portal again and search for it:
   `grep -rF "<token>" "$LABHQ_DATA_DIR" --exclude=bot_token` and the terminal scrollback
   find nothing.
10. Run `uv run labhq onboard --no-serve --non-interactive`. The Discord step passes without
    asking anything and the server shows no new channel or webhook.
11. Failure path: in the portal, turn **Message Content Intent** off and run
    `uv run labhq onboard discord --no-serve --non-interactive`. It fails naming the intent
    and the bot page link, and never prints `labhq is ready.` Turn the intent back on.

The check passes when steps 1 to 11 hold with exactly three manual actions in step 1 to 3.

## Record the result

| Date | labhq commit | OS | Manual actions | Steps passed | Notes |
|---|---|---|---|---|---|
| | | | | | |
