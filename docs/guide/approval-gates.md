# Approval gates

If you already run a self-hosted page that sends its own push and accepts an approval with a
biometric passkey, labhq can hand its heavy approvals to it. The gate decides; labhq executes
what the gate approved, exactly as it does for an approval you confirm yourself.

## How it works

When a gate is configured and `labhq serve` is running:

1. A new heavy approval (push, merge, delete and so on) is posted to the gate with a one-line
   summary of the action and the project's repository path. The gate's request id is kept on
   the approval.
2. labhq polls the gate for that request.
3. The gate's answer settles the approval:

| Gate answer | What labhq does |
|---|---|
| `approved`, proof is a passkey | Approves with confirmation `external_gate` and decider `gate:<name>`, then executes. |
| `approved`, any other proof (for example a password) | Leaves the approval pending and records why. |
| `denied` | Rejects the approval. |
| `expired` | Leaves the approval pending. |
| `pending` | Keeps polling. |

Light approvals are never sent to the gate; they keep their tap.

A request that expired, or that was approved with a weaker proof, is not polled again. Send
it again with `labhq gate resend <approval id>`.

## Configure it

| Variable | Default | Meaning |
|---|---|---|
| `LABHQ_GATE_BASE_URL` | none | The gate's base URL. With the token, this switches the gate on. |
| `LABHQ_GATE_TOKEN` | none | The token labhq sends with every call. |
| `LABHQ_GATE_TOKEN_HEADER` | `X-Gate-Token` | The header that carries the token. |
| `LABHQ_GATE_REQUEST_PATH` | `/internal/request` | Where a request is posted. |
| `LABHQ_GATE_STATUS_PATH` | `/internal/status/{id}` | Where a request's status is read. |
| `LABHQ_GATE_NAME` | `gate` | The name recorded in the decider, `gate:<name>`. |
| `LABHQ_GATE_PASSKEY_PROOFS` | `passkey,face_id,webauthn` | The `via` values that count as a passkey proof. |
| `LABHQ_GATE_TIMEOUT_SECONDS` | `10.0` | The timeout of each call. |
| `LABHQ_PROGRAM_GATE_INTERVAL_SECONDS` | `5.0` | How often labhq polls the gate. |

The full list is in [Configuration](configuration.md).

## What the gate must answer

`POST <base><request path>` with the token header and the JSON body
`{"command": "...", "cwd": "..."}` returns JSON with an `id`.

`GET <base><status path>` (the `{id}` placeholder is replaced) with the same header returns
JSON with `status`, one of `pending`, `approved`, `denied` or `expired`, and `via`, the proof
that decided it.

## Safety

- A heavy approval is resolved only on a passkey proof. Add a proof name to
  `LABHQ_GATE_PASSKEY_PROOFS` only if the gate uses it for a passkey.
- The token is never logged, stored in the database or put in an error message. Keep it in
  the environment of the process, not in a file in a repository.
- Use an `https` URL, or a loopback or private-network address you control.

## Check it

```sh
labhq gate test
```

The command sends a harmless request and prints the gate's answer, for example
`request 7: pending`. For a full check with a real gate and your phone, follow
[the manual check](../checks/approval-gate.md).
