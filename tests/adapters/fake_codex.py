"""A fake `codex` for CI: the Codex CLI's interactive contract, without a model or a network.

It takes the command line the real CLI takes (openai/codex main 86a54b05, checked
2026-10-03): `codex [-c key=value]... [FLAGS] [--] [PROMPT]` and `codex [-c ...] resume
[FLAGS] [--] SESSION_ID [PROMPT]`. Each `-c` value is parsed as TOML, as
codex-rs/utils/cli/src/config_override.rs does, falling back to a plain string when it is not
TOML; `hooks.<Event>` then has to be a list of matcher groups or it is ignored with a warning.
Hooks given on the command line run only with `--dangerously-bypass-hook-trust`, and the
`Stop` and `PreToolUse` hooks get their payload on stdin, exit code 2 blocking a tool call.

The screens come from fixtures/codex/, taken from the Codex TUI's own snapshot tests
(codex-rs/tui/src/{status,chatwidget}/snapshots) at that commit; the manual check in
docs/checks/codex-adapter.md replaces them with live captures when the CLI changes.

Sessions live under `$FAKE_CODEX_HOME/sessions`, one JSON file per id. Prompts are read like a
model would: "sleep" runs a command until Escape interrupts it; "codeword X" is remembered;
"What was the codeword?" recalls it from the resumed session; "git push" calls the shell tool.
"""

import json
import os
import re
import subprocess
import sys
import termios
import tomllib
import tty
import uuid
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).with_name("fixtures") / "codex"
ESCAPE = "\x1b"
PUSH_COMMAND = "git push origin HEAD"
NO_SESSION = (
    "No saved session found with ID {id}. "
    "Run `codex resume` without an ID to choose from existing sessions."
)


class CodexExitError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").rstrip("\n")


def say(text: str) -> None:
    print(text, flush=True)


def toml_value(raw: str) -> Any:
    try:
        return tomllib.loads(f"_x_ = {raw}")["_x_"]
    except tomllib.TOMLDecodeError:
        return raw.strip().strip("\"'")


def parse_overrides(pairs: list[str]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        if not separator:
            raise CodexExitError(2, f"Invalid override (missing '='): {pair}")
        *parents, leaf = key.strip().split(".")
        node = config
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = toml_value(raw.strip())
    return config


FLAGS = {
    "--dangerously-bypass-approvals-and-sandbox": "yolo",
    "--yolo": "yolo",
    "--dangerously-bypass-hook-trust": "hook_trust",
    "--no-alt-screen": "inline",
}


def parse_args(argv: list[str]) -> tuple[dict[str, Any], set[str], list[str]]:
    overrides: list[str] = []
    flags: set[str] = set()
    words: list[str] = []
    args = iter(argv)
    for arg in args:
        if arg == "--":
            words.extend(args)
        elif arg in ("-c", "--config"):
            overrides.append(next(args, ""))
        elif arg in FLAGS:
            flags.add(FLAGS[arg])
        elif arg.startswith("-"):
            raise CodexExitError(2, f"error: unexpected argument '{arg}' found")
        else:
            words.append(arg)
    return parse_overrides(overrides), flags, words


class Hooks:
    def __init__(self, config: dict[str, Any], trusted: bool) -> None:
        self._groups: dict[str, list[dict[str, Any]]] = {}
        for event, groups in config.get("hooks", {}).items():
            if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
                say(f"⚠ failed to parse TOML hooks in <session-flags>/config.toml: {event}")
                continue
            if not trusted:
                say(f"⚠ {event} hook from <session-flags> is not trusted; skipped")
                continue
            self._groups[event] = groups

    def run(self, event: str, payload: dict[str, Any], tool: str | None = None) -> list[str]:
        """Run the event's command hooks; the stderr of each one that exits 2."""
        blocks: list[str] = []
        for group in self._groups.get(event, []):
            matcher = group.get("matcher")
            matches_all = tool is None or matcher in (None, "", "*")
            if not matches_all and not re.fullmatch(str(matcher), tool or ""):
                continue
            for handler in group.get("hooks", []):
                if handler.get("type") != "command":
                    continue
                result = subprocess.run(
                    ["sh", "-c", str(handler["command"])],
                    input=json.dumps({"hook_event_name": event, **payload}),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 2:
                    blocks.append(result.stderr.strip())
        return blocks


class Session:
    def __init__(self, home: Path, session_id: str, cwd: Path) -> None:
        self.path = home / "sessions" / f"{session_id}.json"
        self.id = session_id
        self.cwd = cwd
        self.messages: list[dict[str, str]] = []

    @classmethod
    def load(cls, home: Path, session_id: str) -> "Session":
        path = home / "sessions" / f"{session_id}.json"
        if not path.exists():
            raise CodexExitError(1, NO_SESSION.format(id=session_id))
        data = json.loads(path.read_text(encoding="utf-8"))
        session = cls(home, session_id, Path(data["cwd"]))
        session.messages = data["messages"]
        return session

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"cwd": str(self.cwd), "messages": self.messages}
        self.path.write_text(json.dumps(data), encoding="utf-8")


class Codex:
    def __init__(self, session: Session, hooks: Hooks) -> None:
        self.session = session
        self.hooks = hooks
        self.turns = 0

    def header(self, name: str) -> None:
        for line in fixture(name).splitlines():
            say(f"directory: {self.session.cwd}" if line.startswith("directory:") else line)

    def turn(self, prompt: str) -> None:
        self.turns += 1
        say(f"› {prompt}")  # noqa: RUF001  (Codex's own prompt glyph)
        self.session.messages.append({"role": "user", "text": prompt})
        reply = self.answer(prompt)
        if reply is None:
            say(fixture("interrupted.txt"))
            self.session.save()
            return
        say(f"• {reply}")
        self.session.messages.append({"role": "assistant", "text": reply})
        self.session.save()
        self.hooks.run("Stop", self.payload(last_assistant_message=reply, stop_hook_active=False))

    def answer(self, prompt: str) -> str | None:
        if "sleep" in prompt:
            say("• Running sleep 30")
            say("• Working (0s • esc to interrupt)")
            while read_key() != ESCAPE:
                pass
            return None
        if "git push" in prompt:
            return self.shell(PUSH_COMMAND)
        if "codeword?" in prompt:
            return self.recall() or "I was not told a codeword."
        return "OK"

    def recall(self) -> str | None:
        for message in self.session.messages:
            found = re.search(r"codeword (\S+)", message["text"])
            if message["role"] == "user" and found:
                return found.group(1)
        return None

    def shell(self, command: str) -> str:
        payload = self.payload(tool_name="Bash", tool_input={"command": command})
        blocks = self.hooks.run("PreToolUse", payload, tool="Bash")
        if blocks:
            return f"Command blocked by PreToolUse hook: {blocks[0]}"
        result = subprocess.run(command.split(), capture_output=True, text=True, check=False)
        say(f"• Ran {command}")
        return f"`{command}` exited {result.returncode}"

    def payload(self, **fields: Any) -> dict[str, Any]:
        return {
            "session_id": self.session.id,
            "turn_id": str(self.turns),
            "cwd": str(self.session.cwd),
            "model": "gpt-5.1-codex",
            "permission_mode": "bypassPermissions",
            "transcript_path": None,
            **fields,
        }

    def idle(self) -> None:
        line = ""
        while True:
            key = read_key()
            if key in ("\r", "\n"):
                self.command(line.strip())
                line = ""
            elif key != ESCAPE:
                line += key

    def command(self, line: str) -> None:
        if line == "/status":
            say(fixture("status_limits.txt"))
        elif line:
            self.turn(line)


def read_key() -> str:
    key = os.read(sys.stdin.fileno(), 1)
    if not key:
        raise CodexExitError(0, "")
    return key.decode("utf-8", errors="replace")


def open_session(words: list[str], home: Path, config: dict[str, Any]) -> tuple[Session, str]:
    cwd = Path.cwd()
    if words[:1] != ["resume"]:
        prompt = words[0] if words else ""
        return Session(home, str(uuid.uuid4()), cwd), prompt
    if len(words) < 2:
        raise CodexExitError(
            2, "fake codex: the resume picker is not reproduced; pass a SESSION_ID"
        )
    session = Session.load(home, words[1])
    if session.cwd != cwd and config.get("tui", {}).get("resume_cwd") != "current":
        say(f"Session was recorded in {session.cwd}; resume there or in {cwd}?")
        while read_key() not in ("\r", "\n"):
            pass
    session.cwd = cwd
    return session, words[2] if len(words) > 2 else ""


def run(argv: list[str]) -> None:
    config, flags, words = parse_args(argv)
    if "yolo" not in flags:
        raise CodexExitError(
            3, "fake codex: approval prompts are not reproduced; pass the bypass flag"
        )
    session, prompt = open_session(words, Path(os.environ["FAKE_CODEX_HOME"]), config)
    codex = Codex(session, Hooks(config, trusted="hook_trust" in flags))
    codex.header("resume_header.txt" if session.messages else "startup.txt")
    for message in session.messages:
        say(("› " if message["role"] == "user" else "• ") + message["text"])  # noqa: RUF001
    if prompt:
        codex.turn(prompt)
    codex.idle()


def main() -> int:
    saved = termios.tcgetattr(sys.stdin.fileno()) if sys.stdin.isatty() else None
    if saved is not None:
        tty.setcbreak(sys.stdin.fileno())
    try:
        run(sys.argv[1:])
    except CodexExitError as stop:
        if str(stop):
            print(str(stop), file=sys.stderr, flush=True)
        return stop.status
    finally:
        if saved is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
