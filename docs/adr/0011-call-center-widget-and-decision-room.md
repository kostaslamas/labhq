# 0011. The Call Center widget and the decision room

## Status

Accepted (2026-10-10). Amends ADR 0009: the CEO's prompt carries one pinned line besides the
owner's words.
ADR 0012 later allows a `/ceo` tab for settings (no chat).

## Date

2026-10-10

## Context

Issue #199. The web UI had a CEO chat page. The owner wants chat in one place only, a
floating assistant, and everything else as boards, cards and forms. When a CEO proposal does
not suit them, they want to talk it over with the CEO and the project's manager together.

## Decision

- **One chat.** `CallCenterWidget` sits in the app shell, bottom right, on every page that has
  the shell. It replaces `/ceo` and its sidebar entry. Reports stay cards on Today. A test
  (`freeText.spec.ts`) reads the web app and fails on a text input outside the widget that is
  not listed with where its text goes, on a `/ceo` route, and on any other caller of the two
  message endpoints.
- **Context is data.** The widget sends `context: {route, project_id, pinned: {kind, id,
  options}}` with the owner's words. The server reads the pinned proposal itself
  (`labhq.meetings.proposal`, a registry by kind: `report`, `approval`) and stores a short
  summary beside the words. The CEO's prompt is the owner's text, then one line
  `[Pinned by the owner: report #12 - ...]`. `owner_message_of_run` still returns the words
  only, so the CEO cannot quote the pin as something the owner said.
- **Buttons only point.** A CEO message may end with `[[approve approval:12]]`,
  `[[reject approval:12]]` or `[[show report:3]]`. The API strips the markers into `actions`.
  Approve and reject open the approval's own confirmation (a tap, or a passkey when heavy);
  `show` navigates. A marker decides nothing.
- **Voice is not rebuilt.** The Call Center's voice is the MCP connector in the owner's AI app.
  The microphone button says so; the web gets no speech code.
- **The `decision` kind.** A live room, registered in `labhq.meetings.kinds` with `live`,
  `includes_ceo` and `owner_starts`. Participants are the CEO (facilitator) and the project's
  managers. Only the owner can approve its start: the CEO's `start_meeting` refuses the kind,
  `propose_decision_room` only requests it, and `MeetingService.start` refuses a start approved
  with an agent's own confirmation. The request records a cost estimate (the recent average
  cost of a run of those agents times the turn cap plus the minutes), shown with the approval.
- **A live thread, not rounds.** `DecisionRoom.advance` runs every agent that has not yet
  answered the owner's latest message, in seat order, then stops. The owner's entry is
  recorded first (`add_owner_entry`) and the agents answer in the background. An adopted tmux
  manager mid-step makes the room record `waiting_agent_id` and `waiting_reason`; the widget
  offers Esc through the control keys. `LABHQ_MEETINGS_DECISION_TURN_CAP` (default 12) counts
  agent turns; at the cap the room writes its minutes and ends with `end_reason = turn_cap`.
  Every run leaves a transcript entry with its run id, so `meeting_cost_micros` counts all of it.
- **Nothing executes by itself.** The minutes record decisions. Each action item becomes an
  unassigned task and a `decision_action` approval (light, `owner_only`). The approval service
  refuses an agent's confirmation for an `owner_only` action; the executor assigns the task and
  wakes its assignee only after the owner approved. A pinned card shows "Decided: ..." from the
  room's decisions.
- **Models.** Turns and minutes use each agent's own settings. `LABHQ_MEETINGS_MINUTES_CONFIG`
  is laid over the facilitator's run settings for the minutes: the seam for the lighter model
  policy of #198, which sets no keys yet.

## Consequences

- The CEO's prompt is no longer only the owner's words when something is pinned.
- A room's action items cost the owner one tap each; an unconfirmed one stays a backlog task.
- The room's turns run in the API process. A restart mid-turn leaves the room running until
  the owner speaks again or closes it.
- A manager that spoke before the owner's newest message arrived is not asked again for it
  until the owner writes once more.
