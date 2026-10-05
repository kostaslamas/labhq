"""An interactive fake with a per-turn signal for stable CEO tmux tests."""

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("--resume")
    parser.add_argument("--signal", required=True)
    parser.add_argument("prompt")
    args = parser.parse_args()
    session_id = args.resume or args.session
    path = Path(args.signal)

    def answer(prompt: str) -> None:
        text = f"pid={os.getpid()} session={session_id} prompt={prompt}"
        print(text, flush=True)
        path.write_text(
            json.dumps({"session_id": session_id, "last_assistant_message": text}),
            encoding="utf-8",
        )

    answer(args.prompt)
    for line in sys.stdin:
        if line.strip():
            answer(line.strip())


if __name__ == "__main__":
    main()
