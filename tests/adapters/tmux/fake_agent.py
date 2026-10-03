"""A fake interactive CLI agent for the tmux adapter tests. It never calls a model.

It prints its session and working directory, acts on the words of its prompt, prints the
turn-end marker and then idles like an interactive agent, answering `/usage`.

Prompt words: `ENV` reports what the worker can see of credentials; `PUSH` tries to publish
(through the push guard hook first when `--hook` is given); `WAIT` blocks until Ctrl-C;
`TRUST` shows Claude Code's folder-trust dialog and goes on only when Down and Enter select
the trust option; `LOGIN` shows a login dialog nobody may answer; `STALL` prints once and
then goes quiet.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import tty
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


# The screen of the end-to-end run that found the hang (2026-10-03), as the pane showed it.
TRUST_DIALOG = """\
Accessing workspace: {cwd}

Quick safety check: Is this a project you created or one you trust? (Like your own code,
a well-known open source project, or work from your team). If not, take a moment to
review what's in this folder first.

Claude Code'll be able to read, edit, and execute files here.

{options}

Enter to confirm \u00b7 Esc to cancel"""
MARK = "\u276f"
LOGIN_DIALOG = "Select login method:\n \u276f 1. Claude account\n   2. Anthropic Console"


def trust_dialog() -> None:
    """Claude Code 2.1.288: unnumbered options, cursor on "No, exit", Down moves it."""
    options = ["No, exit", "Yes, I trust this folder"]
    chosen = 0
    tty.setcbreak(sys.stdin.fileno())
    while True:
        lines = [f" {MARK} {o}" if n == chosen else f"   {o}" for n, o in enumerate(options)]
        print(TRUST_DIALOG.format(cwd=Path.cwd(), options="\n".join(lines)), flush=True)
        key = sys.stdin.read(1)
        if key == "\x1b":
            chosen = min(chosen + 1, 1) if sys.stdin.read(2) in ("[B", "OB") else chosen
        elif key in ("\r", "\n"):
            break
    if chosen != 1:
        print("exiting without trust", flush=True)
        sys.exit(1)
    print("trusted", flush=True)


def login_dialog() -> None:
    print(LOGIN_DIALOG, flush=True)
    threading.Event().wait()


def stall() -> None:
    print("starting", flush=True)
    threading.Event().wait()


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
        "TRUST": trust_dialog,
        "LOGIN": login_dialog,
        "STALL": stall,
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
