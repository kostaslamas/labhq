# Notifications

A voice assistant cannot call you back, so labhq reaches your phone through a notifier:
approvals that wait for you, questions from agents, health incidents and plan-usage warnings.
ntfy is the default and needs no account; Telegram is the optional alternative. One notifier
is active at a time, chosen by `LABHQ_NOTIFY_KIND`.

Notifications go through an outbox in the database: a send that fails is retried with backoff
(`LABHQ_NOTIFY_MAX_ATTEMPTS`, `LABHQ_NOTIFY_BACKOFF_BASE_SECONDS`,
`LABHQ_NOTIFY_BACKOFF_MAX_SECONDS`), and nothing is lost while the network or the server is
down. `labhq serve` sends them as they come; `labhq notify flush` sends what is due by hand.

Check the setup at any time:

```sh
labhq notify test
```

## ntfy (default)

[ntfy](https://ntfy.sh) delivers to its phone app by topic name. On the first run labhq picks
a long random topic, keeps it in the data directory, and `labhq onboard` shows a QR code that
subscribes the ntfy app to it.

| Variable | Default | Meaning |
|---|---|---|
| `LABHQ_NOTIFY_KIND` | `ntfy` | The notifier |
| `LABHQ_NOTIFY_NTFY_SERVER` | `https://ntfy.sh` | The ntfy server; set your own if you host one |
| `LABHQ_NOTIFY_NTFY_TOPIC` | a random topic | A topic of your own instead |
| `LABHQ_NOTIFY_NTFY_PRIORITY` | `high` | The ntfy priority of every message |

On the public server, anyone who knows a topic can read it. Keep the topic long and random,
and do not reuse one you have published, or run your own ntfy server. A notification says
what waits for you; the decision itself is taken in labhq, never by replying to it.

## Telegram

1. In Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot` and follow the
   prompts. Copy the token it gives you.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<token>/getUpdates` in a browser and copy `chat.id` from the
   answer.
3. Set the three variables and restart labhq:

   ```sh
   export LABHQ_NOTIFY_KIND=telegram
   export LABHQ_NOTIFY_TELEGRAM_TOKEN=<token>
   export LABHQ_NOTIFY_TELEGRAM_CHAT_ID=<chat id>
   labhq notify test
   ```

The bot token is a credential. Keep it in your shell or a secrets manager, never in a file in
a repository. labhq rewrites it out of its HTTP logs, and never stores it in the database.

All notifier settings are listed in [Configuration](configuration.md#labhqnotifysettingsnotifysettings).
