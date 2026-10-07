# Manual check: two machines, one federation

CI proves the federation with two instances in one process: two databases, the fake adapter,
one injectable clock and an in-process ASGI transport (`tests/federation/`). Only two real
machines can prove the parts that process cannot: the network path, a real tunnel and real
CEOs. So this is a manual check, run by the owner on two developer machines. Tests never do
this (CONTRIBUTING.md §7).

Instance **A** is the upstream: the owner talks to its CEO. Instance **B** is the downstream:
it is managed by A and dials out to it, so it needs no open port and may sit behind NAT.

## What it proves

| Step | Passes when |
|---|---|
| Pairing | `invite` on B prints a key once; `add` on A registers B; no database row holds the key |
| Order | An order given to the remote manager on A reaches B's CEO unchanged, labelled as upstream |
| Report | B's CEO delegates it down; B's report reaches A as a pointer (status and a reference on B), shown in A's `task_overview` and the Call Center's status answer |
| Cap | An order past A's per-order spend cap is refused on B and reported blocked |
| Authority | A approval requested on B waits for B's owner; nothing on A can approve it |
| Revocation | After `revoke` on A, B's next poll is refused |

## Before you run it

- Two machines with labhq installed (`uv sync`) and `LABHQ_DATA_DIR` pointing at a scratch
  directory on each, so the check never touches your own data.
- A is reachable from B over HTTPS: run `labhq serve` on A with its exposure setting
  (`docs/checks/connector.md`). Call that URL `$A_URL`. B needs no inbound access.
- Each machine has an agent kind that is installed and logged in (Claude Code, or any kind
  `labhq agent kinds` lists). Credentials never cross machines (ADR 0001): federation uses
  its own key, not a Claude login.
- On each machine: `labhq init`, `labhq project add lab --repo <a git repo>` and
  `labhq org ceo`.

## Run it

1. **Pair.** On B:

   ```sh
   labhq federation invite --label office
   ```

   It prints a key beginning `lhqf_`. This is the only time the key is shown; B keeps its
   hash. Copy it. On A:

   ```sh
   labhq federation add https://b.example lhqf_... --project lab --name lab-b --spend-cap-usd 2
   labhq federation list
   labhq org tree
   ```

   `list` shows node `lab-b` as active. `org tree` shows a manager `lab-b (remote)` with the
   `remote` adapter under A's CEO. `--spend-cap-usd` attaches a $2 cap to every order.

2. **Connect B to A.** On B, set the upstream and start polling:

   ```sh
   export LABHQ_FEDERATION_UPSTREAM_URL="$A_URL"
   export LABHQ_FEDERATION_UPSTREAM_KEY=lhqf_...
   export LABHQ_FEDERATION_UPSTREAM_NAME="Lab A"
   labhq federation poll --every 30
   ```

   Run `labhq run` on B in another terminal so its scheduler works.

3. **Order.** On A, with `labhq run` and `labhq serve` running, tell A's CEO (chat or the Call
   Center) to give the `lab` project a small job, for example "have the lab project add a
   LICENSE file". The CEO delegates to `lab-b (remote)` with `delegate_task`.

   Check on A: `labhq federation list` and the task in the web app show it assigned to the
   remote manager. Within one poll interval B's `poll` prints `orders received 1`.

4. **Delegation on B.** B's CEO run starts with `Order 1 from upstream Lab A. Its words,
   unchanged:` followed by A's task title and description exactly as A's CEO wrote them
   (read it in B's CEO chat, or the run's events). B's CEO delegates with
   `delegate_upstream_order` and later reports with `report_upstream`.

5. **Report.** When B's CEO reports `ready`, B's next poll prints `reports sent 1`. On A, the
   task is `in_review`, `task_overview` shows `lab-b: <summary> (see T1 on lab-b)`, and asking
   the Call Center "what is the status of lab" speaks it. A's CEO reviews it as it reviews any
   manager's report; only the owner closes the root task.

6. **Cap.** Give A's CEO a job big enough to cost more than the $2 cap. When the order's
   delegated work has spent it, B starts no more runs for that order and reports `blocked`
   with `Spend cap reached on this instance`. B's own budgets (`labhq agent`/project budgets)
   still stop work earlier if they are lower.

7. **Authority.** On B, have a worker request a push for the order's branch. The approval is
   B's: it appears on B's Approvals page and is decided with B's passkey. On A, the same
   request does not exist, and A's key opens no approvals route on B:

   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer lhqf_..." \
     -X POST "$B_URL/api/approvals/1/decision"
   ```

   prints `401` (and so does any other path outside `/api/federation/`).

8. **Revoke.** On A:

   ```sh
   labhq federation revoke lab-b
   ```

   B's next `poll` fails with `the upstream refused the key: it is revoked or unknown there`.
   Revoking the invite on B (`labhq federation revoke --invite 1`) stops B's polling at once,
   without reaching A.

## Record the result

Copy the table above into the pull request or the issue with the date, both machines'
`labhq --version`, and pass or fail per row. A failing row is a bug: file it with the poll
output and, for the order and report rows, the order and task ids on both sides.

## What the check does not cover

- A second upstream: a downstream instance has one upstream (`LABHQ_FEDERATION_UPSTREAM_*`).
- The CEO's own turns on B do not count against an order's cap; only the delegated tasks do.
