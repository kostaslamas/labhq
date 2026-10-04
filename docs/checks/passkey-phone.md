# Manual check: approve a heavy action from a phone with a passkey

CI proves the page with a virtual authenticator on an emulated 390x844 screen
(`web/e2e/approve-phone.spec.ts`). Only a real phone can prove that the notification opens the
page, that the device asks for Face ID or a fingerprint, and that the approved action runs. This
is a manual check. Tests never do it (CONTRIBUTING.md §7).

## What it proves

The approval notification on your phone carries a link to `/approve/<id>` on your public
address. Opening it asks for your passkey, shows what will run, asks for the passkey again
to approve, and the action then executes.

## Before you run it

- A stable public address reaches labhq, for example Tailscale Funnel or your own domain
  (see `docs/guide/exposure.md`). A quick tunnel changes host on every start and breaks the
  passkey, so do not use one for this check.
- `LABHQ_PUBLIC_URL` is set to that address, without a path, and `labhq serve` runs with it.
- The phone receives labhq notifications (`docs/checks/notifier.md`). If the notification
  has no link, `LABHQ_PUBLIC_URL` is not set in the process that created the approval.
- The phone has a screen lock and biometrics enabled.

## Run it

1. On the machine labhq runs on, print an enrollment link for the public address:

   ```sh
   uv run labhq passkey enroll --url "$LABHQ_PUBLIC_URL"
   ```

2. Open the link on the phone, create the passkey and confirm with Face ID or a fingerprint.
   Passing: the page says the passkey is created.
3. Create a heavy approval. Nothing executes until you approve it:

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
       approval = await service.request("delete_branch", {"members": ["developer"], "lead": "manager"})
       print(f"approval A{approval.id} requested")
       await engine.dispose()

   asyncio.run(main())
   PY
   uv run labhq notify flush
   ```

   Passing: the phone shows "Approval needed" and tapping it opens
   `<public address>/approve/<id>`.
4. With no session on the phone, the page shows only a sign-in button. Tap it and confirm with
   Face ID or a fingerprint. Passing: the page now shows the action, its risk and what will
   run, and no horizontal scrolling is needed.
5. Tap "Approve with passkey" and confirm again. Passing: the page shows the decision
   "Confirmed with a passkey", and `uv run labhq approvals list` shows the approval decided.
6. Check the action ran: the approval page shows its execution result under the decision.
   Passing: the result is recorded and matches what the action should have done.
7. Open the same link again. Passing: it shows the decided state and no buttons.
8. Repeat from step 3 and cancel the second prompt. Passing: the approval stays pending and the
   page says so.

## Record the result

Add a line below with the date, the phone and OS, the public address type, and whether steps
2 to 8 passed.

| Date | Phone and OS | Public address | Steps 2 to 8 |
|---|---|---|---|
