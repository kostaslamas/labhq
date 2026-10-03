"""A working agent's pane for the screen tests. It never calls a model.

It prints its progress, then each line the test writes into the `progress` pipe of its
working directory, and echoes anything typed into it: a key sent to its pane would show.
"""

import sys
import threading
from pathlib import Path

PROGRESS = Path("progress")


def print_progress() -> None:
    while True:
        # Blocks until the test opens the pipe; the file ends when the test closes it.
        with PROGRESS.open(encoding="utf-8") as pipe:
            for line in pipe:
                print(line.rstrip(), flush=True)


def main() -> None:
    threading.Thread(target=print_progress, daemon=True).start()
    print("manager: working on the login form", flush=True)
    for line in sys.stdin:
        print(f"received: {line.rstrip()}", flush=True)


if __name__ == "__main__":
    main()
