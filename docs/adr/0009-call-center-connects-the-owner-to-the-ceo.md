# 0009. The Call Center connects the owner to the CEO

## Status

Accepted (2026-10-06). Amends ADR 0004: the Call Center no longer delivers to working agents
or interrupts them.

## Date

2026-10-06

## Context

The owner's decision in issue #167: the owner talks to labhq through the Call Center, and
the Call Center connects them to the global CEO. The CEO passes orders down to managers and
workers. Before this, the Call Center went around the CEO: a voice `order` created a task for
a project's manager, and `deliver` and `interrupt` passed the owner's words straight to any
agent the owner named.

The owner set four rules. Orders reach the CEO in the owner's exact words. A clearer wording
is sent only after the owner confirms it in the same call. Status answers come from the
reports of workers and their supervisors, not from the CEO. Prompts stay minimal.

## Decision

- One path to the CEO. `labhq.ceochat_send.send_owner_message` queues an `owner_message`
  wakeup, the same one the web chat uses, so the scheduler, the budget and the backup retry
  treat both alike. The web route, the Call Center's `send_to_ceo` and the MCP `order` tool
  all use it. The CEO's prompt is its own memory section and then the agreed text, nothing
  else.
- What is sent is stored first. `send_to_ceo` takes the id of a request of this call and
  sends its stored words. `propose_wording` stores a wording next to the request and sends
  nothing. `confirm_wording` takes the proposal and a later request of the same call; a yes
  in the owner's stored words sends the proposal, a no rejects it, anything else leaves it
  unsent. A request stored before the proposal cannot confirm it, and the original words and
  a confirmed wording of the same request are never both sent.
- The Call Center creates no task and talks to no manager or worker: `deliver` and
  `interrupt` are gone from its tools. Answering an agent's pending question (`answer`) stays,
  because it replies to the agent rather than ordering it.
- Status questions use the `reports` answer: per project, each agent's latest task report,
  review or status file, with the reporter, the age, the task status and the last run.
  Screens stay the fallback for stale reports.
- A merge order still only requests the heavy `merge` approval, approved with the passkey.

## Consequences

- The owner's words reach working agents only through the CEO, so an urgent stop waits for
  the CEO's turn instead of an interrupt.
- Call Center messages queue behind the CEO's current answer instead of being refused, as
  the web chat refuses a second turn; owner messages are never coalesced, so none is lost.
- Confirmation is read from the owner's stored words with a small yes and no vocabulary. A
  wording the owner did not clearly accept is not sent; the owner can repeat the order.
