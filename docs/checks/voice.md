# Manual check: brief, ask_ceo and get_reply by voice

CI proves the parts with the fake agent (`tests/callcenter/calls/`, `tests/mcp/tools/`):
`ask_ceo` returns a ticket in under 2 s while the agent takes 30 s, `get_reply` and
`ask_ceo` with `wait_seconds` long-poll (below), `get_reply` redeems it
with a speakable answer, a follow-up inside the call window resumes the same session, and
the CEO gets only the owner's words or a wording the owner confirmed. Only a real voice
client and a real model prove the scenario end to end, so this is a manual check, recorded
on video by the owner. Tests never do it (CONTRIBUTING.md section 7).

## What it proves

Plan section 10, Phase 2: at least one app (Claude or ChatGPT) completes the scenario
brief, then ask_ceo, then get_reply, by voice, through the labhq connector.

## Before you run it

- The connector check passes (`docs/checks/connector.md`): `cloudflared` is installed and a
  Claude custom connector can reach labhq through a quick tunnel.
- A labhq data directory exists with at least one project and one approved agent, and
  some work done, so `brief` has something to say (`docs/checks/phase-1-demo.md` leaves
  such a database).
- The Call Center agent runs on the `claude` adapter, the pinned Claude Code binary is on
  `PATH` (or set `LABHQ_CLI_PATH`), and you are logged in or have set `ANTHROPIC_API_KEY`
  (ADR 0001). Its budget defaults to 2 USD per budget period; set
  `LABHQ_CALLCENTER_AGENT_BUDGET_MICROS` before its first call to change it, or edit its
  `agents` row afterwards.
- Screen recording is on, with the phone's or the computer's audio.

## Run it

1. Start the connector:

   ```sh
   uv run labhq serve --expose quick-tunnel
   ```

   Wait for `Connector URL: https://<words>.trycloudflare.com/mcp/<token>` and add it as a
   custom connector in Claude (or as a connector in ChatGPT developer mode). `labhq serve`
   runs the whole program, so the CEO answers the orders it gets; `labhq mcp serve
   --expose` serves the connector alone, without the scheduler.
2. Open a voice conversation with the connector enabled. Start recording.
3. Say: "Give me my brief." Passing: the app calls `brief` and reads a short, plain answer:
   no table, no list markers, no JSON.
4. Say: "Ask the CEO what the worker is doing and whether anything is blocked." Passing:
   the app calls `ask_ceo` and says it has a ticket within about 2 seconds, or, when it
   passes `wait_seconds`, reads the answer directly.
5. Say: "Get the reply." Passing: the app calls `get_reply` with the same ticket and the
   call itself waits, up to 25 seconds by default and never more than 50, until the answer is
   ready, so the app does not have to call again by itself. If it hears "Still working on
   it", it calls `get_reply` again with that ticket and never asks the question again; the
   answer then names the agent and what it is doing, in two to five spoken sentences.
   A run that cannot go on (a dialog nobody can answer, no progress for five minutes) ends
   as failed, and `get_reply` speaks "could not finish that one" instead of "Still working".
6. Within five minutes, say: "Ask the CEO what that agent does next." Passing: the answer
   follows from the previous one (the call resumed the same session). Confirm afterwards:

   ```sh
   DB="$(uv run python -c 'from labhq.settings import Settings; print(Settings().data_dir)')/labhq.sqlite3"
   sqlite3 "$DB" "select id, session_id, status from calls order by id desc limit 2;"
   ```

   Both questions belong to one call with one `session_id`.
7. Stop recording and the server.

## Pass criteria

- Steps 3 to 6 pass in one take, on video.
- Every answer was readable aloud as heard: no table, no JSON, no markdown read out.
- `select count(*) from cost_events where agent_id = (select id from agents where role =
  'call_center')` grew by one per `ask_ceo`: every call's cost is recorded.
- Nothing reached the CEO that you did not say or confirm (`select reason from
  wakeup_requests where source = 'owner_message'` holds only your words or a wording you
  said yes to), and status questions woke nobody.

## Record the run

Add a line with the date, the app and device, the video's location, and whether steps 3
to 6 passed.

| Date | App and device | Video | Steps 3 to 6 | Notes |
|---|---|---|---|---|
| 2026-10-03 | scripted MCP client, `labhq serve` | none | not a voice run | End-to-end over MCP found the trust-dialog hang, the instant `get_reply` and the missing `serve --expose`; all three fixed in #133. The owner's voice run is still to be recorded. |
