# 0004. The Call Center: an always-on program and one agent per call

## Status

Accepted (2026-10-03).

## Date

2026-10-03

## Context

Plan §3 has the owner talk to the orchestrator ("CEO") by voice through an MCP connector.
Asking the CEO, or a project manager, what is going on interrupts the agent that does the
work. Most status questions do not need a decision maker; they need someone who reads.

A single long-lived agent cannot serve two calls at once. An agent runs one turn at a
time: in tmux, two messages typed together mix in its input; through the SDK, a second
query joins the same conversation and the answers mix.

The MCP server is stateless (Phase 0 spike), so it does not know where a call begins or
ends. Every tool call arrives on its own.

ADR 0003 runs agents in tmux. The owner wants every agent there, the Call Center included.

## Decision

### Three parts

1. The program: the labhq engine and its public MCP server. It always runs. Questions it
   can answer from the database (projects, tasks, approvals, spend, health) it answers
   itself, in under 2 s, without any agent.
2. A Call Center agent per call: it handles what needs reading and judgement, then ends.
   It never decides, assigns or approves; it reads and routes.
3. The working agents (CEO, managers, leads, workers): they report their status as they
   work and are not disturbed by questions.

### A call is a window of time

The first `ask_ceo` starts a Call Center agent in its own session on the private tmux
server (ADR 0003) and returns a ticket. A later `ask_ceo` within the call window (default
5 minutes, configurable) belongs to the same call: the agent resumes the same session, so
follow-up questions keep their context. After the window the call closes; the next
question starts a fresh agent. Two calls at the same time are two agents.

### Agents report status to a file the engine ingests

Every working agent keeps `.labhq/status.md` in its worktree up to date, with the fields of
`labhq.economy.Handoff` (`summary`, `done`, `next`, `blockers`, `refs`) plus `questions`.
A file works with every agent, since every agent can write files. The engine ingests each
change into the database with its time.

At the end of each turn the engine checks whether the agent updated the file during that
turn, and asks it to if it did not.

### Fresh or stale is a mechanical rule

A status is fresh when it is newer than the agent's last activity (its latest `run_events`
row or screen change). The Call Center answers from a fresh status. When the status is
stale, it captures the agent's tmux pane and reads it. It never sends keys to a working
agent's pane.

### The Call Center's tools come over stdio, not the network

The Call Center gets labhq's internal tools from an MCP server that its CLI starts as a
child process over stdio (`labhq mcp internal`): read the database, read an agent's status
and events, capture a pane, deliver a message, interrupt an agent. Nothing listens on a
port, so nothing reaches the tunnel. It gets no shell and no file-writing tools. Whether
each CLI accepts a stdio MCP server, and how to remove its built-in tools, is verified when
this is built.

Pane text and logs contain repository text, which can carry instructions. With no tool
that writes code or runs commands, such text has nothing to act on.

### Questions from agents reach the owner at once

A question an agent writes under `questions` becomes a row with its asker, project and
task. The program notifies the owner through the notifier (ntfy by default) with the
question's text; no agent is needed to send it.

When the owner answers during a call, the Call Center matches the answer to a question id
and asks back when it is not sure which question is meant. The answer goes to the asker
recorded on the row, never to an agent the model picks. Answering is a conditional update
on a pending row, so two calls cannot both answer the same question.

### Delivery waits for the turn to end, unless the owner says interrupt

A message for a working agent is queued as a wakeup and delivered when its current turn
ends. If the owner tells the Call Center to interrupt, it interrupts the agent, delivers
the message, and the agent continues with the same context. Interrupt is a light action:
committed work stays, only the current turn is lost.

Plan §5, rule 7 holds: a voice client never approves a heavy action, whatever the Call
Center relays.

## Consequences

- Plan §2 gains the Call Center next to the CEO, as a reader and router. Plan §3 changes
  "talk to the CEO" to "talk to the Call Center"; tool names stay as they are until Phase 2
  locks the list.
- New tables: status updates, questions from agents, and calls (session id, last activity,
  window). Each is an Alembic migration.
- The Call Center has its own agent row and its own budget. Every call costs at least one
  model turn plus one usage reading (ADR 0003).
- Plan §6 gains the invariant that an agent question is answered at most once.
- The program's database answers and the notifier land with Phase 2. The per-call agent,
  status files and pane reading need the tmux adapter (ADR 0003) and land with it.
