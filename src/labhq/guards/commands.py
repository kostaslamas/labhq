"""See through the programs that run other programs: `env`, `sudo`, `sh -c`, `xargs` and more.

Every program the guard understands is a registry entry mapping its name to a handler. A
handler reads the arguments and yields steps: a denial, a nested script for the shell
parser, or the words of the command it wraps.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Deny:
    reason: str


@dataclass(frozen=True)
class Nested:
    script: str


@dataclass(frozen=True)
class Wrapped:
    words: tuple[str, ...]
    # True when the wrapper appends arguments read at run time, as `xargs` does.
    open_ended: bool = False


type Step = Deny | Nested | Wrapped
type Handler = Callable[[Sequence[str], bool], Iterator[Step]]

# Words that open or close a shell construct and precede the command they guard.
RESERVED_WORDS = frozenset(
    {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "coproc"}
)
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
# Characters through which the shell computes a word at run time.
_EXPANSION_CHARS = frozenset("$`*?[{")


def is_dynamic(word: str) -> bool:
    return bool(_EXPANSION_CHARS.intersection(word))


def strip_prefix_words(words: Sequence[str]) -> list[str]:
    """Drop reserved words and `NAME=value` assignments in front of a command."""
    index = 0
    while index < len(words) and (
        words[index] in RESERVED_WORDS or _ASSIGNMENT.match(words[index])
    ):
        index += 1
    return list(words[index:])


def program_name(word: str) -> str:
    return PurePosixPath(word).name


@dataclass(frozen=True)
class Options:
    """How a program spells its options before the operands start."""

    takes_value: frozenset[str] = frozenset()
    # Options whose value is itself a shell script, such as `su -c`.
    script_values: frozenset[str] = frozenset()


NO_OPTIONS = Options()


def split_options(args: Sequence[str], options: Options) -> tuple[list[str], list[str]]:
    """Return (scripts carried in option values, operands after the options)."""
    scripts: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            index += 1
            break
        if not word.startswith("-") or word == "-":
            break
        name, has_inline, inline = word.partition("=")
        if name.startswith("--") and has_inline:
            value: str | None = inline
        elif word in options.takes_value:
            index += 1
            value = args[index] if index < len(args) else None
            name = word
        elif word[:2] in options.takes_value and not word.startswith("--"):
            name, value = word[:2], word[2:]
        else:
            value = None
        if value is not None and name in options.script_values:
            scripts.append(value)
        index += 1
    return scripts, list(args[index:])


def prefix_wrapper(
    options: Options = NO_OPTIONS,
    *,
    operands: int = 0,
    open_ended: bool = False,
    assignments: bool = False,
    joined: bool = False,
) -> Handler:
    """A program that runs the command written after its options and `operands` words.

    `joined` programs hand that command to a shell as one string (`watch`, `ssh`).
    """

    def handle(args: Sequence[str], outer_open_ended: bool) -> Iterator[Step]:
        scripts, rest = split_options(args, options)
        yield from (Nested(script) for script in scripts)
        rest = rest[operands:]
        if assignments:
            rest = strip_prefix_words(rest)
        if not rest:
            return
        if joined:
            yield Nested(" ".join(rest))
            return
        yield Wrapped(tuple(rest), open_ended=open_ended or outer_open_ended)

    return handle


_SHELL_OPTIONS = Options(takes_value=frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}))


def shell(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    """`sh -c SCRIPT`, `bash -lc SCRIPT` and the like; running a script file is opaque."""
    if open_ended:
        yield Deny("a shell whose script arrives at run time")
        return
    flags = [word for word in args if word.startswith("-") and not word.startswith("--")]
    _, operands = split_options(args, _SHELL_OPTIONS)
    if any("c" in flag[1:] for flag in flags) and operands:
        yield Nested(operands[0])


def evaluate(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    if open_ended:
        yield Deny("eval of text that arrives at run time")
        return
    yield Nested(" ".join(args))


def trap(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    _, operands = split_options(args, NO_OPTIONS)
    if operands:
        yield Nested(operands[0])


def alias(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    for word in args:
        _, has_value, value = word.partition("=")
        if has_value:
            yield Nested(value)


_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_TERMINATORS = frozenset({";", "+"})


def find(args: Sequence[str], open_ended: bool) -> Iterator[Step]:
    command: list[str] | None = None
    for word in args:
        if command is None:
            command = [] if word in _FIND_ACTIONS else None
            continue
        if word in _FIND_TERMINATORS:
            yield Wrapped(tuple(command), open_ended=True)
            command = None
            continue
        command.append(word)
    if command:
        # `\;` reaches us as a separator, so the action runs to the end of the command.
        yield Wrapped(tuple(command), open_ended=True)


def _values(*names: str) -> frozenset[str]:
    return frozenset(names)


# A new wrapper is a new row here, never a new branch in the analyser.
WRAPPERS: dict[str, Handler] = {
    "env": prefix_wrapper(
        Options(
            takes_value=_values("-u", "--unset", "-C", "--chdir", "-S", "--split-string"),
            script_values=_values("-S", "--split-string"),
        ),
        assignments=True,
    ),
    "command": prefix_wrapper(),
    "builtin": prefix_wrapper(),
    "exec": prefix_wrapper(Options(takes_value=_values("-a"))),
    "nohup": prefix_wrapper(),
    "setsid": prefix_wrapper(),
    "unbuffer": prefix_wrapper(),
    "chronic": prefix_wrapper(),
    "time": prefix_wrapper(Options(takes_value=_values("-f", "-o", "--format", "--output"))),
    "nice": prefix_wrapper(Options(takes_value=_values("-n", "--adjustment"))),
    "ionice": prefix_wrapper(Options(takes_value=_values("-c", "-n", "-p", "--class"))),
    "stdbuf": prefix_wrapper(Options(takes_value=_values("-i", "-o", "-e"))),
    "timeout": prefix_wrapper(
        Options(takes_value=_values("-s", "-k", "--signal", "--kill-after")), operands=1
    ),
    "sudo": prefix_wrapper(
        Options(takes_value=_values("-u", "-g", "-h", "-p", "-C", "-D", "-R", "-r", "-t", "-U"))
    ),
    "doas": prefix_wrapper(Options(takes_value=_values("-u", "-C"))),
    "su": prefix_wrapper(
        Options(takes_value=_values("-c", "--command"), script_values=_values("-c", "--command")),
        operands=1,
    ),
    "runuser": prefix_wrapper(
        Options(
            takes_value=_values("-u", "-g", "-c", "--command"),
            script_values=_values("-c", "--command"),
        )
    ),
    "script": prefix_wrapper(
        Options(takes_value=_values("-c", "--command"), script_values=_values("-c", "--command")),
        operands=1,
    ),
    "flock": prefix_wrapper(
        Options(
            takes_value=_values("-w", "-E", "-c", "--timeout", "--command"),
            script_values=_values("-c", "--command"),
        ),
        operands=1,
    ),
    "xargs": prefix_wrapper(
        Options(takes_value=_values("-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a")),
        open_ended=True,
    ),
    "watch": prefix_wrapper(Options(takes_value=_values("-n", "--interval")), joined=True),
    "ssh": prefix_wrapper(
        Options(takes_value=frozenset("-" + c for c in "BbcDEeFIiJLlmOoPpQRSWw")),
        operands=1,
        joined=True,
    ),
    "eval": evaluate,
    "trap": trap,
    "alias": alias,
    "find": find,
    "busybox": prefix_wrapper(),
    **dict.fromkeys(("sh", "bash", "dash", "zsh", "ksh", "ash"), shell),
}
