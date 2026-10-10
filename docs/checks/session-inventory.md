# Manual check: session inventory on a real machine

The automated tests use fixture stores in each tool's documented layout and the fake adapter.
Run this once on a developer machine that has real sessions, and record the result below.

1. Set the scan scope, then confirm it holds. `labhq sessions roots add ~/Developer` (use the folder
   that holds your projects; `labhq onboard` offers the same question, and the web page
   `/session-scan` does it with your passkey). `labhq sessions roots` lists it. Then
   `labhq sessions scan --no-report` ends with `scope: looked in <roots>; N sessions left out`:
   check that a session you know lives elsewhere is counted there and not listed. Ask the Call
   Center "ψάξε και στο ~/Developer": it must change nothing and answer with the page link. With
   no root set the scan says `machine-wide: no scope set`.
2. `labhq sessions scan --no-report`. Every project you expect appears; running agents show
   `waiting for input` or `idle`; Cursor IDE chats show `idle` and are not resumable.
3. Compare one OpenCode, one Cursor CLI and one Cursor IDE session with the tool's own list.
   If a store layout changed, update `labhq.inventory.stores` and its fixture builder.
4. `labhq sessions analyse <project>` shows an estimate and an approval. Approve it with
   `labhq approvals approve <id>`; open the md file under `<data dir>/inventory/analyses/`.
5. `labhq sessions close <project> <pid>` on an idle agent, then approve; the process ends
   and the conversation can be resumed.

Result (date, tools, versions, outcome):
