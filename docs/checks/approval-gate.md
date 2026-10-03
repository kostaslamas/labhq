# Manual check: a heavy approval passes through an external gate

CI proves the protocol against `httpx.MockTransport` (`tests/approvals/gates/`). Only a real
gate and a real passkey prove that your gate answers as labhq expects, so this is a manual
check. Tests never do it (CONTRIBUTING.md §7).

## What it proves

A push approval is sent to your gate, you approve it there with a biometric passkey, and
labhq publishes the branch without any confirmation at the labhq terminal.

## Before you run it

- A self-hosted approval gate that follows the protocol in
  [Approval gates](../guide/approval-gates.md#what-the-gate-must-answer), reachable from the
  machine that runs labhq, and a passkey enrolled in it.
- Set the gate in the environment of `labhq serve` and of the commands below:

  ```sh
  export LABHQ_GATE_BASE_URL=<your gate's base URL>
  export LABHQ_GATE_TOKEN=<your gate's token>
  ```

  Set `LABHQ_GATE_TOKEN_HEADER`, `LABHQ_GATE_REQUEST_PATH` or `LABHQ_GATE_STATUS_PATH` if
  your gate differs from the defaults.
- A labhq data directory with a project whose task has an unpublished commit, as in
  [the push guard check](push-guard.md).

## Run it

1. Confirm the connection. Passing: the command prints `request <id>: pending` and your
   phone shows a request named "labhq gate test".

   ```sh
   uv run labhq gate test
   ```

   Deny that request on the phone.
2. Start the program in one terminal: `uv run labhq serve`.
3. Request a push approval for the task, as in the push guard check. Passing: within a few
   seconds your phone shows a request that names the push, the branch and a short commit.
4. Approve it on the phone with your biometric passkey. Passing: within a few seconds
   `uv run labhq approvals list --status executed` shows the push, and the branch exists on
   the remote.
5. Request a second push. Deny it on the phone. Passing: the approval is `rejected` and
   nothing was pushed.
6. Request a third push. Approve it with a password if your gate offers one. Passing: the
   approval stays pending, and its record says it was approved by a proof that is not a
   passkey. Run `uv run labhq gate resend <approval id>` and approve with the passkey to
   finish it.
7. Search the terminal output of every step and the `serve` log for your token. Passing: it
   appears nowhere.

## Record the result

Add a line below with the date, the gate, the device, and whether steps 1, 4, 5, 6 and 7
passed.

| Date | Gate and device | Step 1 | Step 4 | Step 5 | Step 6 | Step 7 |
|---|---|---|---|---|---|---|
