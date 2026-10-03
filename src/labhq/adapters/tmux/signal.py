"""The command an agent runs to tell labhq something: `python -m labhq.adapters.tmux.signal`.

`turn PATH [PAYLOAD]` records that a turn ended; `statusline PATH` records the Claude Code
statusline JSON. The payload is the last argument when the agent appends one (Codex
`notify`), otherwise stdin (Claude Code hooks and statusline). The file is replaced
atomically, so the engine never reads half a document.
"""

import sys
from pathlib import Path

# What the statusline shows in the pane; the numbers go to the file, not the screen.
STATUSLINE_TEXT = "labhq"
CHANNELS = frozenset({"turn", "statusline"})


def write_atomically(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] not in CHANNELS:
        print("usage: signal {turn,statusline} PATH [PAYLOAD]", file=sys.stderr)
        return 2
    channel, path = args[0], Path(args[1])
    payload = args[2] if len(args) > 2 else sys.stdin.read()
    write_atomically(path, payload)
    if channel == "statusline":
        print(STATUSLINE_TEXT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
