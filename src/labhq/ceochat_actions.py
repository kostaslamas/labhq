"""Action buttons at the end of a CEO message: `[[approve approval:12]]` becomes a button.

The CEO writes a marker on its own last lines; the chat strips it from the text and offers it
as a button. A button only points at something: approving still goes through the approval's
own confirmation (a tap, or a passkey for a heavy one), so a marker never decides anything.
`VERBS` is data: a verb and the kinds of thing it may name.
"""

import re
from dataclasses import dataclass

VERBS: dict[str, frozenset[str]] = {
    "approve": frozenset({"approval"}),
    "reject": frozenset({"approval"}),
    "show": frozenset({"approval", "report", "meeting", "task", "project"}),
}
MAX_ACTIONS = 4
_MARKER = re.compile(r"^\[\[(?P<verb>[a-z]+) (?P<kind>[a-z]+):(?P<id>\d{1,9})\]\]$")


@dataclass(frozen=True)
class ReplyAction:
    verb: str
    target_kind: str
    target_id: int


def split_actions(reply: str) -> tuple[str, list[ReplyAction]]:
    """The reply without its trailing markers, and the markers as actions."""
    lines = reply.rstrip().splitlines()
    actions: list[ReplyAction] = []
    while lines and (match := _MARKER.match(lines[-1].strip())):
        verb, kind = match["verb"], match["kind"]
        if kind not in VERBS.get(verb, frozenset()):
            break
        actions.append(ReplyAction(verb, kind, int(match["id"])))
        lines.pop()
    actions.reverse()
    return "\n".join(lines).rstrip(), actions[:MAX_ACTIONS]
