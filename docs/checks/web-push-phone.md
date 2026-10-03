# Manual check: a phone receives an approval push from the installed web app

CI proves signing, delivery to every subscription and pruning against a mocked push
endpoint (`tests/notify/test_webpush.py`), and the service worker's tap handler against a
fake worker scope (`web/src/push/worker.spec.ts`). Only a phone and the vendor's push service
can prove that a real notification appears and opens the app. Tests never do it
(CONTRIBUTING.md §7).

## What it proves

A phone with labhq installed from its Home Screen (iOS 16.4 or later) or as an installed web
app (Android) subscribes with your passkey session, and a new approval reaches it as a push
notification that opens labhq when you tap it.

## Before you run it

- labhq is reachable from the phone over https: `LABHQ_PUBLIC_URL` is set, for example by
  `uvx labhq onboard` (a Cloudflare quick tunnel) or your own domain. A push service accepts
  subscriptions only from a secure origin.
- A passkey is enrolled for that address (`labhq passkey enroll`, [Passkeys](../guide/passkeys.md)).
- The notifier is the default: `LABHQ_NOTIFY_KIND` is unset or `webpush`.
- `labhq serve` is running, so the outbox sends as notifications arrive.

## Run it

1. On the phone, open the public address and sign in with the passkey.
2. Install the app. On iOS: Share, then Add to Home Screen, and open labhq from the new icon.
   On Android: the browser menu, then Install app. Passing: the app opens without browser
   chrome (standalone).
3. Open Notifications in the sidebar. Before installing, on iOS the page must say to add the
   app to the Home Screen first. Passing: after installing, it shows Enable notifications.
4. Press Enable notifications on this device and allow the system prompt. Passing: the page
   says the device receives notifications.
5. On the machine that runs labhq, create an approval. It is only a request; nothing executes
   until you approve it:

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
   ```

   Passing: within a few seconds the phone shows "Approval needed" naming `A<id>`.
6. Lock the phone, wait for a second approval and tap the notification. Passing: labhq opens
   in the installed app. Until the phone approval page ships (#67) the notification carries
   no address of its own and opens the app's start page; after it, it opens `/approve/<id>`.
7. Turn notifications off on the page and create a third approval. Passing: the phone shows
   nothing, and `uv run labhq notify flush` reports the send as retried, not delivered.

The VAPID private key must appear in no terminal output and no log line:
`grep -r vapid_private "$LABHQ_DATA_DIR"/*.log` prints nothing, and
`stat -c %a "$LABHQ_DATA_DIR/vapid_private.pem"` prints `600`.

## Record the result

Add a line below with the date, the phone and OS version, and whether steps 3 to 7 passed.

| Date | Device and OS | Step 3 | Step 4 | Step 5 | Step 6 | Step 7 |
|---|---|---|---|---|---|---|
