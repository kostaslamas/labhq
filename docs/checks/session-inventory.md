# Manual check: session inventory on a real machine

The automated tests use fixture stores in each tool's documented layout and the fake adapter.
Run this once on a developer machine that has real sessions, and record the result below.

1. `labhq sessions scan --no-report`. Every project you expect appears; running agents show
   `waiting for input` or `idle`; Cursor IDE chats show `idle` and are not resumable.
2. Compare one OpenCode, one Cursor CLI and one Cursor IDE session with the tool's own list.
   If a store layout changed, update `labhq.inventory.stores` and its fixture builder.
3. `labhq sessions analyse <project>` shows an estimate and an approval. Approve it with
   `labhq approvals approve <id>`; open the md file under `<data dir>/inventory/analyses/`.
4. `labhq sessions close <project> <pid>` on an idle agent, then approve; the process ends
   and the conversation can be resumed.

Result (date, tools, versions, outcome):
