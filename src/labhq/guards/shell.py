"""Split a shell command line into simple commands without running it.

The push guard must see every command a line would run, so this errs towards finding too
much: text inside quotes that looks like a substitution is analysed as a script as well.
"""

import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field

# `\n` is an operator here, not whitespace: a newline separates commands as `;` does.
_OPERATOR_CHARS = ";&|()<>\n"
_REDIRECT_CHARS = frozenset("<>")
_SUBSTITUTION_OPENERS = ("$(", "<(", ">(")
_HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2")


class UnparsableCommandError(ValueError):
    """The line cannot be tokenised, so nothing can be said about what it runs."""


@dataclass
class ParsedScript:
    commands: list[list[str]] = field(default_factory=list)
    # Text the shell executes in another context: substitutions and here-strings.
    nested: list[str] = field(default_factory=list)
    # Here-document bodies; read leniently because most of them are file contents.
    documents: list[str] = field(default_factory=list)
    # (operator, target) of every redirection; the read-only classifier denies writes.
    redirections: list[tuple[str, str]] = field(default_factory=list)


def parse(script: str, *, lenient: bool = False) -> ParsedScript:
    """Return the simple commands of `script` and the text it runs elsewhere.

    `lenient` retries an untokenisable script with its quotes removed, which keeps every
    word visible at the cost of merging some of them.
    """
    outer, documents = _split_heredocs(script.replace("\\\n", " "))
    parsed = ParsedScript(nested=list(_substitutions(outer)), documents=documents)
    try:
        tokens = _tokens(outer)
    except UnparsableCommandError:
        if not lenient:
            raise
        tokens = _tokens(outer.replace("'", " ").replace('"', " "))
    _collect(tokens, parsed)
    return parsed


def _tokens(script: str) -> list[str]:
    lexer = shlex.shlex(script, posix=True, punctuation_chars=_OPERATOR_CHARS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    # Bash starts a comment only at a word boundary; shlex would swallow `a#b; git push`.
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as error:
        raise UnparsableCommandError(str(error)) from error


def _is_operator(token: str) -> bool:
    return bool(token) and all(char in _OPERATOR_CHARS for char in token)


def _collect(tokens: list[str], parsed: ParsedScript) -> None:
    current: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not _is_operator(token):
            current.append(token)
            continue
        if not _REDIRECT_CHARS.intersection(token):
            if current:
                parsed.commands.append(current)
            current = []
            continue
        # A redirection keeps the command going; drop its fd number and its target.
        if current and current[-1].isdigit():
            current.pop()
        target = ""
        if index < len(tokens) and not _is_operator(tokens[index]):
            target = tokens[index]
            if token == "<<<":
                parsed.nested.append(target)
            index += 1
        parsed.redirections.append((token, target))
    if current:
        parsed.commands.append(current)


def _substitutions(script: str) -> Iterator[str]:
    """Yield the bodies of `$(...)`, `<(...)`, `>(...)` and backticks, quoted or not."""
    index = 0
    while index < len(script):
        if script.startswith(_SUBSTITUTION_OPENERS, index):
            end = _closing_paren(script, index + 2)
            yield script[index + 2 : end]
            index = end + 1
        elif script[index] == "`":
            end = script.find("`", index + 1)
            end = len(script) if end < 0 else end
            yield script[index + 1 : end]
            index = end + 1
        else:
            index += 1


def _closing_paren(script: str, start: int) -> int:
    depth = 1
    for index in range(start, len(script)):
        depth += {"(": 1, ")": -1}.get(script[index], 0)
        if depth == 0:
            return index
    # Unbalanced: the rest of the line is the body, which is the conservative reading.
    return len(script)


def _split_heredocs(script: str) -> tuple[str, list[str]]:
    """Separate here-document bodies from the command lines that introduce them."""
    outer: list[str] = []
    documents: list[str] = []
    pending: list[tuple[str, bool]] = []
    body: list[str] = []
    for line in script.split("\n"):
        if pending:
            delimiter, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                documents.append("\n".join(body))
                body = []
                pending.pop(0)
            else:
                body.append(line)
            continue
        outer.append(line)
        pending = [(m.group(3), m.group(1) == "-") for m in _HEREDOC.finditer(line)]
    if body:
        # An unterminated here-document runs to the end of the input in bash too.
        documents.append("\n".join(body))
    return "\n".join(outer), documents
