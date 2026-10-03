"""A fake interactive CLI agent for the tmux adapter tests. It never calls a model.

It prints its session and working directory, acts on the words of its prompt, prints the
turn-end marker and then idles like an interactive agent, answering `/usage`.

Prompt words: `ENV` reports what the worker can see of credentials; `PUSH` tries to publish
(through the push guard hook first when `--hook` is given); `WAIT` blocks until Ctrl-C.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

TURN_END = "LABHQ-FAKE-TURN-END"
CREDENTIAL_NAMES = ("SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN", "LABHQ_CLIENT_ONLY")
USAGE_LINE = "Usage: $0.42 spent this session, 37% of the 5h limit used"


def report_environment() -> None:
    for name in CREDENTIAL_NAMES:
        print(f"env {name}={os.environ.get(name, '-')}")
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=example.invalid\n\n",
        capture_output=True,
        text=True,
        check=False,
    )
    print("credential=leaked" if "password=leaked" in result.stdout else "credential=none")


def push(hook: str | None) -> None:
    command = "git push origin HEAD"
    if hook:
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}
        payload["tool_input"] = {"command": command}
        verdict = subprocess.run(
            shlex.split(hook), input=json.dumps(payload), capture_output=True, text=True
        )
        if verdict.returncode == 2:
            print("push=denied-by-hook")
            return
    result = subprocess.run(shlex.split(command), capture_output=True, text=True, check=False)
    print(f"push-exit={result.returncode}")


def wait_for_interrupt() -> None:
    print("waiting", flush=True)
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        print("interrupted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("--resume")
    parser.add_argument("--hook")
    parser.add_argument("prompt")
    args = parser.parse_args()
    session = args.resume or args.session
    print(f"fake-agent session={session} resumed={bool(args.resume)} cwd={Path.cwd()}")
    actions = {
        "ENV": report_environment,
        "WAIT": wait_for_interrupt,
        "PUSH": lambda: push(args.hook),
    }
    for word in args.prompt.split():
        actions.get(word, lambda: None)()
    print(TURN_END, flush=True)
    for line in sys.stdin:
        if line.strip() == "/usage":
            print(USAGE_LINE, flush=True)


if __name__ == "__main__":
    main()
