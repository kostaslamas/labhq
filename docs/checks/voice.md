# Manual check: brief, ask_ceo and get_reply by voice

CI proves the parts with the fake agent (`tests/callcenter/calls/`, `tests/mcp/tools/`):
`ask_ceo` returns a ticket in under 2 s while the agent takes 30 s, `get_reply` redeems it
with a speakable answer, a follow-up inside the call window resumes the same session, and
`deliver` and `interrupt` refuse anything the owner did not ask for. Only a real voice
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
   uv run labhq mcp serve --expose quick-tunnel
   ```

   Wait for `Connector URL: https://<words>.trycloudflare.com/mcp/<token>` and add it as a
   custom connector in Claude (or as a connector in ChatGPT developer mode). To let
   `interrupt` reach running agents, use `uv run labhq serve` behind your own tunnel
   instead: only that process holds the scheduler's live runs.
2. Open a voice conversation with the connector enabled. Start recording.
3. Say: "Give me my brief." Passing: the app calls `brief` and reads a short, plain answer:
   no table, no list markers, no JSON.
4. Say: "Ask the CEO what the worker is doing and whether anything is blocked." Passing:
   the app calls `ask_ceo` and says it has a ticket within about 2 seconds.
5. Wait a few seconds and say: "Get the reply." Passing: the app calls `get_reply` with
   the same ticket. If it hears "Still working on it", it asks again; the answer then names
   the agent and what it is doing, in two to five spoken sentences.
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
- Nothing was delivered to a working agent unless you asked for it
  (`select * from deliveries` is empty, or holds only your own words).

## Record the run

Add a line with the date, the app and device, the video's location, and whether steps 3
to 6 passed.

| Date | App and device | Video | Steps 3 to 6 | Notes |
|---|---|---|---|---|
