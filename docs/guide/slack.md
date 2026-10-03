# Meetings in Slack

labhq can mirror every meeting into Slack: a channel per project, a thread per meeting, and
each agent posting under its own name and avatar. You join a meeting by replying in its
thread. The database stays the source of truth; Slack is an optional mirror (plan §2.1, §12),
so conversations pass through Slack's servers only if you turn this on.

Slack needs no public URL: labhq reads replies over Socket Mode, a WebSocket it opens itself.

## Create the app

1. Open <https://api.slack.com/apps>, choose **Create New App > From an app manifest**, pick
   your workspace, and paste [`slack-manifest.yaml`](slack-manifest.yaml). Create the app.
2. **Install App > Install to Workspace** and allow. Copy the **Bot User OAuth Token**
   (`xoxb-…`).
3. **Basic Information > App-Level Tokens > Generate Token and Scopes**: name it `socket`,
   add the scope `connections:write`, generate, and copy the token (`xapp-…`).
4. In Slack, open your profile, **⋮ > Copy member ID** (`U…`). Only this member's replies
   are read back.

Both tokens are credentials. Keep them in your shell or a secrets manager, never in a file in
the repository. labhq never logs them, never stores them in its database and never puts them
in an error message.

## What the app may do

The manifest grants exactly what the adapter calls (`labhq.chat.slack.BOT_SCOPES`); a test
keeps the two in step.

| Scope | Why |
|---|---|
| `channels:manage` | `conversations.create`: one public channel per project, created once |
| `chat:write` | `chat.postMessage`: the thread root and every post |
| `chat:write.customize` | a per-message `username` and `icon_url`, so each agent has its own name |
| `channels:history` | the `message.channels` event: replies in labhq's channels reach Socket Mode |
| `connections:write` | app-level token only: opens the Socket Mode connection |

The bot creates its channels, so it is a member of each and needs no invitation. It only sees
channels it is a member of; replies anywhere else never reach labhq.

## Configure labhq

```sh
export LABHQ_SLACK_BOT_TOKEN='xoxb-…'
export LABHQ_SLACK_APP_TOKEN='xapp-…'
export LABHQ_SLACK_OWNER_ID='U…'
# Optional: channels are named <prefix><project>, "labhq-" by default.
export LABHQ_SLACK_CHANNEL_PREFIX='labhq-'
```

Without both tokens Slack is simply not registered and meetings stay in the database. With
Discord configured as well, both mirrors run.

## Behaviour worth knowing

- A project's channel is found again through labhq's `chat_bindings` after a restart. If a
  channel with the same name already exists and labhq did not create it, labhq stops and says
  so instead of adopting it: rename or archive that channel, or change the prefix.
- Messages over 4000 characters are split at line, then sentence, then word boundaries and
  posted in order.
- Rate limits (HTTP 429) are retried after Slack's `Retry-After`.
- Bot messages, labhq's own posts, other members' messages, edits and anything outside a
  labhq thread are ignored. A reply you also send to the channel still counts.
- Slack's free plan hides history older than 90 days; labhq's database keeps the meeting.

To check a new setup end to end, run the [manual check](../checks/slack-meetings.md).
