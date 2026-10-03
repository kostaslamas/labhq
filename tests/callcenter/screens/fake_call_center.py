"""A fake Call Center CLI for the tmux tests. It never calls a model.

It prints its session, whether it resumed, and the tool servers it was given, waits until
the test opens the line (it holds an exclusive lock on the `line` file until then), then
ends its turn and idles like an interactive agent.
"""

import argparse
import fcntl
import json
import sys
from pathlib import Path

TURN_END = "LABHQ-FAKE-TURN-END"
LINE = Path("line")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("--resume")
    parser.add_argument("--mcp", default="[]")
    parser.add_argument("--no-builtin-tools", action="store_true")
    parser.add_argument("prompt")
    args = parser.parse_args()
    servers = [" ".join(argv) for argv in json.loads(args.mcp)]
    print(f"fake-call-center session={args.resume or args.session} resumed={bool(args.resume)}")
    print(f"builtin-tools={not args.no_builtin_tools} servers={servers}", flush=True)
    with LINE.open("a") as line:
        fcntl.flock(line, fcntl.LOCK_SH)
    print(TURN_END, flush=True)
    for _ in sys.stdin:
        pass


if __name__ == "__main__":
    main()
