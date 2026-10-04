# The Call Center

The Call Center is how you talk to labhq by voice. labhq has no voice code: it is an MCP
server (Streamable HTTP) that you add as a connector to the AI app you already use. You speak
to that app in its own voice mode, and it calls labhq's tools when it needs to.

```text
You ──voice──> AI app (Claude, ChatGPT)
                  │  MCP over HTTPS
                  ▼
             labhq MCP server ──> engine ──> agents
                  │
                  └──> notifier (ntfy / Telegram) ──> you
```

## Add the connector

You need the connector URL, `https://<public address>/mcp/<token>`. `labhq onboard` prints it
with a QR code; otherwise build it from your [exposure](exposure.md) and `labhq mcp token`.
The secret path is the credential, so leave every authentication field of the connector
form empty.

### Claude

1. In Claude (web or desktop), open **Settings**, then **Connectors**, and choose **Add custom
   connector**.
2. Name it `labhq` and paste the connector URL. Add it.
3. In a conversation, enable the `labhq` connector from the tools menu. On the phone, connectors
   added on the web are available too; start voice mode and ask "what did the teams do
   today?".

### ChatGPT

1. In ChatGPT on the web, open **Settings**, then **Apps & Connectors**. Custom connectors may
   need **Developer mode**, under **Advanced settings**, depending on your plan.
2. Create a connector, name it `labhq`, paste the connector URL and choose no authentication.
3. Enable it in a conversation and talk to it in voice mode.

Menu names in both apps change from time to time; look for "custom connector". Which plans
can add one is up to each vendor. Consumer Gemini does not accept custom MCP connectors.

## The tools

| Tool | Kind | What it does |
|---|---|---|
| `brief` | read | Today in a few spoken sentences: finished work, decisions waiting, today's spend |
| `inbox` | read | What waits for you: approvals (`A12`) and agent questions (`Q7`) |
| `health` | read | Whether the machines that run the agents are up, and open incidents |
| `meeting_minutes` | read | A meeting's participants, decisions, action items and cost; the latest one unless you name it |
| `ask_ceo` | write | A question that needs reading and judgement; returns a ticket at once |
| `get_reply` | read | The answer for an `ask_ceo` ticket, or "still working" |
| `answer` | write | Your own words as the answer to an agent's question |
| `order` | write | A new task in a project; without an assignee, it wakes the active manager |
| `decide` | write, destructive | Approve or reject a pending approval |

Read tools carry `readOnlyHint`, so apps run them without asking. `decide` carries
`destructiveHint`, so the app confirms with you first. Answers are written to be heard:
short sentences, no tables, no JSON.

Questions the database can answer (projects, tasks, approvals, cost, health) come back from
labhq directly in under two seconds, with no model involved. Questions that need judgement go
through `ask_ceo` to a Call Center agent started for the call. Questions a few minutes apart
(`LABHQ_CALLCENTER_CALL_WINDOW_SECONDS`) belong to the same call and share its context.

## What it will do

- Tell you what happened, what waits for you and how the machines are.
- Find out what an agent is doing, from the status the agent keeps or, when that is stale,
  by reading the agent's screen. It never interrupts an agent to ask.
- Pass your answer to an agent that asked you something, as you said it.
- Create tasks, and approve or reject light actions after your clear yes.
- Deliver a message to an agent at the end of its turn, or interrupt it at once when you
  explicitly ask for that in the same call.

## What it will not do

- **Approve a heavy action.** Push, merge, deleting, team creation, budget overruns and
  changes to a machine stay pending; the Call Center tells you to confirm them with your
  passkey (or, until passkeys land in the web UI, with `labhq approvals approve <id>`).
- **Put words in your mouth.** A message to an agent is your own words from the current call,
  stored with the call, never text a model composed. Screens and logs can carry instructions,
  and the agents run with broad permissions, so this rule has no exceptions.
- **Type into a working agent.** It reads screens; it never sends keys to an agent mid-turn.
- **Run commands or edit files.** The Call Center agent's own tools read the database, the
  status, events and screens and deliver messages. It has no shell and writes no files.
- **Call you.** It cannot start a conversation; anything urgent reaches you as a
  [notification](notifications.md).

See [Security](security.md) for how the connector is authenticated and exposed.
