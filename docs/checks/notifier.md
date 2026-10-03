# Manual check: a phone receives an approval notification

CI proves delivery against `httpx.MockTransport` (`tests/notify/`). Only a phone can prove
that the real ntfy service shows the message, so this is a manual check. Tests never do it
(CONTRIBUTING.md §7).

## What it proves

A phone subscribed to your labhq topic receives, within a few seconds, the notification that
a new approval creates, and `labhq notify test` reaches the same phone.

## Before you run it

- The ntfy app is installed on the phone (Android, iOS or the web app at ntfy.sh). No
  account is needed.
- A labhq data directory exists: `uv run labhq init`.
- The default notifier is ntfy on `https://ntfy.sh`. To use another server or a fixed topic,
  set `LABHQ_NOTIFY_NTFY_SERVER` or `LABHQ_NOTIFY_NTFY_TOPIC`.

## Run it

1. Print the topic. labhq generates it once and keeps it in the data directory:

   ```sh
   uv run labhq notify test
   cat "$(uv run python -c 'from labhq.settings import Settings; print(Settings().data_dir)')/ntfy_topic"
   ```

   The first command may fail to reach a phone, because nobody subscribes yet. That is fine;
   the second prints the topic.
2. In the ntfy app, subscribe to that topic (the topic is the only secret, so treat it like
   a password).
3. Send the test notification again and confirm the phone shows "labhq test":

   ```sh
   uv run labhq notify test
   ```

4. Create an approval and send the waiting notification. No command creates an approval
   yet, so use the service directly. The approval is only a request; nothing executes until
   you approve it:

   ```sh
   uv run python - <<'PY'
   import asyncio
   from labhq.approvals import ApprovalService
   from labhq.clock import SystemClock
   from labhq.db import create_engine, session_factory
   from labhq.settings import Settings

   async def main() -> None:
       engine = create_engine(Settings().resolved_database_url)
       service = ApprovalService(session_factory(engine), clock=SystemClock())
       approval = await service.request("create_team", {"members": ["developer"], "lead": "manager"})
       print(f"approval A{approval.id} requested")
       await engine.dispose()

   asyncio.run(main())
   PY
   uv run labhq notify flush
   ```

   Passing: `flush` prints `1 notification(s) sent` and the phone shows "Approval needed",
   with the body naming the approval as `A<id>`.
5. Run `uv run labhq notify flush` again. Passing: it prints `0 notification(s) sent` and
   the phone gets nothing new.

## Telegram

Set `LABHQ_NOTIFY_KIND=telegram`, `LABHQ_NOTIFY_TELEGRAM_TOKEN` and
`LABHQ_NOTIFY_TELEGRAM_CHAT_ID`, then repeat steps 3 to 5. The token must appear in no
terminal output and no log line.

## Record the result

Add a line below with the date, the phone and app, and whether steps 3, 4 and 5 passed.

| Date | Device and app | Step 3 | Step 4 | Step 5 |
|---|---|---|---|---|
