# Manual check: this morning's standup minutes by voice

CI proves the parts with rows and the fake agent (`tests/callcenter/answers/test_minutes.py`,
`tests/mcp/tools/test_meetings.py`, `tests/cli/test_meetings.py`): `meeting_minutes` reads the
decisions and action items of a finished standup in sentences that pass `speakable`, picks
the meeting from a spoken reference, asks which one when two fit, and answers in under 2 s
without starting an agent. Only a real voice client proves that the answer sounds right
when read aloud, so this is a manual check, run by the owner (#85). Tests never do it
(CONTRIBUTING.md section 7).

## What it proves

Plan section 10, Phase 3: `meeting_minutes` reads the minutes by voice as spoken text.
Plan section 11, beat 3: you ask for this morning's standup minutes, and the app reads the
decisions and action items.

## Before you run it

- The connector check passes (`docs/checks/connector.md`).
- A labhq data directory with a project whose manager and leads are approved agents on the
  `claude` adapter, the pinned Claude Code binary on `PATH` (or `LABHQ_CLI_PATH`), and a
  Claude login or `ANTHROPIC_API_KEY` (ADR 0001).
- A standup held this morning (UTC). Hold one with:

  ```sh
  uv run labhq meetings start <project> --kind standup
  uv run labhq approvals approve <approval id from the line above>
  uv run labhq meetings start --meeting <meeting id>
  uv run labhq meetings show <meeting id>
  ```

  `show` must list at least one decision and one action item. If the meeting failed, run a
  new one; a failed meeting has no minutes to read.
- For the ambiguity step, a second project with its own standup this morning.
- Screen recording on, with the audio of the phone or the computer.

## Run it

1. Start the connector:

   ```sh
   uv run labhq mcp serve --expose quick-tunnel
   ```

   Add the printed connector URL in Claude (custom connector) or ChatGPT (developer mode).
2. Open a voice conversation with the connector enabled. Start recording.
3. Say: "Read me the minutes of this morning's standup." Passing: the app calls
   `meeting_minutes` without asking for confirmation, then reads who took part, each
   decision, each action item with its owner and task status (for example "Task T12 is not
   started"), and the cost. No table, list marker, JSON or markdown is read out.
4. With two standups this morning, say it again. Passing: the app asks which one, naming
   both meetings (like M4 for one project, M5 for the other). Answer with a project name.
   Passing: it calls `meeting_minutes` again and reads that project's standup.
5. Say: "And the last planning of <project>?" Passing: the planning of that project is
   read, or the answer says there is none.
6. Stop recording and the server.

## Pass criteria

- Steps 3 to 5 pass in one take, on video.
- Each answer arrived within about 2 seconds of the tool call, and no run was started by it:
  `select count(*) from runs` is the same before and after the call.
- What was read aloud matches `labhq meetings show <meeting id>`.

## Record the run

Add a line with the date, the app and device, the video's location, and whether steps 3
to 5 passed.

| Date | App and device | Video | Steps 3 to 5 | Notes |
|---|---|---|---|---|
