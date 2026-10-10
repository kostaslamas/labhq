# Manual check: session inventory on a real machine

The automated tests use fixture stores in each tool's documented layout and the fake adapter.
Run this once on a developer machine that has real sessions, and record the result below.

1. Set the scan scope, then confirm it holds. `labhq sessions roots add ~/Developer` (use the folder
   that holds your projects; `labhq onboard` offers the same question, and the "Where labhq looks for
   sessions" panel on `/projects` does it with your passkey). `labhq sessions roots` lists it. Then
   `labhq sessions scan --no-report` ends with `scope: looked in <roots>; N sessions left out`:
   check that a session you know lives elsewhere is counted there and not listed. Ask the Call
   Center "ψάξε και στο ~/Developer": it must change nothing and answer with the page link. With
   no root set the scan says `machine-wide: no scope set`.
   On `/projects`, open the panel: a repository under the folder that no agent ever worked in must
   appear under "Found in your folders"; "Add project" opens the add form with its folder filled
   in, and "Not interested" removes it for good (the exclusion shows in the panel, where it can
   be removed).
2. Open **Sessions** in the sidebar (it scans by itself the first time). Every project you expect
   appears with its sessions, git facts and a proposed action; **Continue**, **Close** and
   **Analyse** only record approvals (Analyse shows its estimate first), and each project's card
   on `/projects` shows its session counts. The CLI shows the same: `labhq sessions scan --no-report`.
   Running agents show `waiting for input` or `idle`; Cursor IDE chats show `idle` and are not resumable.
3. Optional auto-scan: serve with `LABHQ_INVENTORY_AUTO_SCAN_MINUTES=5`, put a new git repository
   under a scan folder, wait one interval. One notification "1 new project found in <folder>" must
   arrive and the project must be listed on Today; it must not arrive again for the same project,
   and adding or skipping the project removes it from Today.
4. Compare one OpenCode, one Cursor CLI and one Cursor IDE session with the tool's own list.
   If a store layout changed, update `labhq.inventory.stores` and its fixture builder.
5. `labhq sessions analyse <project>` shows an estimate and an approval. Approve it with
   `labhq approvals approve <id>`; open the md file under `<data dir>/inventory/analyses/`.
6. `labhq sessions close <project> <pid>` on an idle agent, then approve; the process ends
   and the conversation can be resumed.

Result (date, tools, versions, outcome):
