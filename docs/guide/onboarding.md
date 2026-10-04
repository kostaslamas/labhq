# Onboarding: one command to a working labhq

```sh
uvx labhq onboard
```

That one command takes an empty data directory to a working system: a database, a connector
for Claude or ChatGPT on your phone, a public URL that reaches it, and notifications on your
phone. It needs no account with any third party. Each account (a stable tunnel, a Telegram
bot, a Discord server) is an optional upgrade later.

## What it does

Onboarding runs a fixed list of steps. For each one it first reports what already exists,
then does what it can by itself, and asks you only for what it cannot do.

| Step | What labhq does | What you might do |
|---|---|---|
| Database | Creates the data directory and runs the migrations | Nothing |
| Connector token | Issues the MCP connector token, stored with mode 0600 | Nothing |
| Public URL | Starts the MCP server and a Cloudflare quick tunnel to it | Install `cloudflared` if it is missing |
| Notifications | Prepares Web Push; with `LABHQ_NOTIFY_KIND=ntfy` keeps a random ntfy topic and sends one test notification | Open the web app on your phone and enable notifications (on iOS, add it to the Home Screen first) |
| Model login | Checks that Claude Code is logged in, or that `ANTHROPIC_API_KEY` is set | Log in to Claude Code once, or set the key |

Before anything else it also reports whether `cloudflared`, `tailscale` and a Discord token
(`LABHQ_DISCORD_TOKEN`) are present.

Before it says `labhq is ready.` it checks the whole path: one MCP `initialize` call through
the public URL, and, once a device is subscribed (or with ntfy or Telegram), one test
notification that the notifier accepts through labhq's outbox. Before any device has
subscribed to Web Push, onboarding says so and does not fail. If a check
fails, onboarding names the step, exits non-zero and never says ready.

At the end it prints:

- the connector URL, and a QR code of exactly that URL, to add as a custom connector in
  Claude or ChatGPT on your phone;
- with ntfy, the subscribe link and a QR code of it, to open in the ntfy app;
- anything left for later, such as the model login.

Then it keeps serving in the foreground: the MCP server, the scheduler and notifications, behind
the same tunnel and the same URL. Stop it with Ctrl-C. A quick tunnel gets a new URL each time
it starts, so the connector URL changes on every run of `labhq onboard` or
`labhq mcp serve --expose quick-tunnel`. For a URL that stays the same, a later
exposure (Tailscale Funnel, or your own domain) will be an optional upgrade.

## Options

| Option | Effect |
|---|---|
| `--no-serve` | Stop after the checks instead of serving |
| `--non-interactive` | Never prompt: a step that needs you fails with its instruction instead. For CI and scripts |
| `--port N` | Local port for the MCP server (default 8787) |

`LABHQ_DATA_DIR` chooses the data directory. `LABHQ_NOTIFY_NTFY_SERVER` and
`LABHQ_NOTIFY_NTFY_TOPIC` choose a different ntfy server or a topic of your own.

## Running it again

Onboarding is safe to repeat. A second run keeps the database, the connector token and the
ntfy topic, and repeats the end-to-end check. Only the quick tunnel URL is new.

## When `cloudflared` is missing

Onboarding never falls back to a local-only server, because a connector on your phone cannot
reach one. It prints one command for your platform and stops (or, when it runs interactively,
waits until you say it is done):

| Platform | Command |
|---|---|
| macOS | `brew install cloudflared` |
| Debian, Ubuntu, WSL2 Ubuntu | download the `.deb` from Cloudflare's releases, then `sudo dpkg -i` |
| Fedora, RHEL and relatives | download the `.rpm`, then `sudo rpm -i` |
| Windows | `winget install --id Cloudflare.cloudflared` |
| Other Linux | download the binary into `~/.local/bin` |

labhq prints the command; it never runs `sudo` itself.

## Models and your Claude login

labhq starts the unmodified Claude Code binary for its agents. By default that binary uses
the login you already completed with `claude`. If `ANTHROPIC_API_KEY` is set, it uses API
billing instead. labhq never reads, copies or stores your credentials: it only asks the binary
`claude auth status` and reads whether you are logged in (ADR 0001).

On the first run onboarding shows a notice once, and records in the data directory that it
did: you are responsible for staying within your plan's terms. Read Anthropic's
[Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms) and the
[legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance).

The connector and notifications work without a model login; agents need one. If neither is
present, onboarding still finishes and lists the login under "Later".
