"""A fake interactive CLI agent for the adoption tests. It never calls a model.

Its conversation lives in `--store`, outside the checkout, like a real CLI's per-directory
session store: `--continue` picks it up. Every start and end is logged to `drivers.log`,
and a start while another live process holds the store's lock logs `CONFLICT`, so a test
can prove that two processes never drove one conversation.

`--work SECONDS` makes the first turn busy for that long; the turn counts only once it
completes. Each line typed afterwards is logged to `inbox.log` and ends a turn; `/compact`
prints a compaction notice, `/new` starts a new session, `PUSH` runs `git push` and
`STATUS` writes `.labhq/status.md`.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import FrameType

TURN_END = "FAKE-CLI-TURN-END"
COMPACTED = "FAKE-COMPACTED"


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)

    def log(self, name: str, line: str) -> None:
        with (self.path / name).open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    def read(self, name: str, default: str = "") -> str:
        target = self.path / name
        return target.read_text(encoding="utf-8").strip() if target.exists() else default

    def write(self, name: str, text: str) -> None:
        (self.path / name).write_text(text, encoding="utf-8")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def take_lock(store: Store) -> None:
    holder = store.read("lock")
    if holder.isdigit() and int(holder) != os.getpid() and alive(int(holder)):
        store.log("drivers.log", f"CONFLICT {os.getpid()} while {holder} runs")
    store.write("lock", str(os.getpid()))


def release(store: Store) -> None:
    store.log("drivers.log", f"end {os.getpid()}")
    if store.read("lock") == str(os.getpid()):
        (store.path / "lock").unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--signal")
    parser.add_argument("--continue", dest="resume", action="store_true")
    parser.add_argument("--work", type=float, default=0.0)
    args = parser.parse_args()
    store = Store(Path(args.store))
    take_lock(store)
    store.log("drivers.log", f"start {os.getpid()} {'continue' if args.resume else 'fresh'}")

    def on_term(signum: int, frame: FrameType | None) -> None:
        release(store)
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_term)
    session = store.read("session") if args.resume else ""
    if not session:
        session = uuid.uuid4().hex
        store.write("session", session)
    turns = int(store.read("turns", "0"))
    print(f"fake-cli session={session} continued={args.resume} turns={turns} cwd={Path.cwd()}")

    def end_turn() -> None:
        print(TURN_END, flush=True)
        if args.signal:
            Path(args.signal).write_text(json.dumps({"session": session, "at": time.time()}))

    deadline = time.monotonic() + args.work
    step = 0
    while time.monotonic() < deadline:
        step += 1
        print(f"working {step}", flush=True)
        # An Event wait, not a sleep: the conventions guard keeps sleeps out of tests.
        threading.Event().wait(0.1)
    if args.work:
        store.write("turns", str(turns + 1))
    end_turn()
    for line in sys.stdin:
        text = line.strip()
        store.log("inbox.log", text)
        if text == "/compact":
            print(COMPACTED, flush=True)
        elif text == "/new":
            session = uuid.uuid4().hex
            store.write("session", session)
            print(f"fake-cli new session={session}", flush=True)
        elif text == "PUSH":
            result = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True)
            print(f"push-exit={result.returncode}", flush=True)
        elif text == "STATUS":
            status = Path(".labhq") / "status.md"
            status.parent.mkdir(exist_ok=True)
            status.write_text(f"summary: turn {time.time()}\n", encoding="utf-8")
        end_turn()
    release(store)


if __name__ == "__main__":
    main()
