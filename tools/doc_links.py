"""Link check over `README.md` and `docs/`: relative links and anchors resolve, and every
guide page is linked from the guide's index.

External links (`https:`, `mailto:` and the like) are not fetched: CI never touches the
network for a guard. Links inside code and HTML comments are not links and are skipped.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

ROOTS = ("README.md", "docs")
GUIDE = Path("docs/guide")
GUIDE_INDEX = GUIDE / "index.md"

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_CODE = re.compile(r"(`+).+?\1")
# `[text](target "title")` and `![alt](target)`; the target ends at whitespace or `)`.
_INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)"
)
_REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
_HTML_LINK = re.compile(r"""<(?:a|img)\b[^>]*?\b(?:href|src)=["']([^"']+)["']""", re.IGNORECASE)
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HTML_ANCHOR = re.compile(r"""<a\b[^>]*\b(?:name|id)=["']([^"']+)["']""", re.IGNORECASE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(frozen=True)
class Link:
    source: Path
    line: int
    target: str


@dataclass(frozen=True)
class Report:
    failures: list[str]
    checked_files: int
    checked_links: int

    @property
    def ok(self) -> bool:
        return not self.failures


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """Lines outside fenced code, with HTML comments blanked out."""
    text = _COMMENT.sub(lambda match: "\n" * match.group(0).count("\n"), text)
    lines: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opening = _FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            continue
        lines.append((number, line))
    return lines


def links(path: Path) -> list[Link]:
    found: list[Link] = []
    for number, raw in _prose_lines(path.read_text(encoding="utf-8")):
        line = _INLINE_CODE.sub("", raw)
        targets = [match.group(1) for match in _INLINE_LINK.finditer(line)]
        targets += [match.group(1) for match in _HTML_LINK.finditer(line)]
        reference = _REFERENCE.match(line)
        if reference:
            targets.append(reference.group(1))
        found.extend(Link(path, number, target) for target in targets if target)
    return found


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: rendered text, lower case, punctuation dropped."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("`", "").replace("*", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    result: set[str] = set()
    for _, line in _prose_lines(path.read_text(encoding="utf-8")):
        result.update(match.group(1) for match in _HTML_ANCHOR.finditer(line))
        heading = _HEADING.match(line)
        if not heading:
            continue
        base = slug(heading.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def _problem(link: Link, root: Path) -> str | None:
    target = link.target
    if _SCHEME.match(target) or target.startswith("//"):
        return None
    path_part, _, fragment = target.partition("#")
    path_part = unquote(path_part)
    if path_part.startswith("/"):
        resolved = (root / path_part.lstrip("/")).resolve()
    elif path_part:
        resolved = (link.source.parent / path_part).resolve()
    else:
        resolved = link.source.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return f"{target} points outside the repository"
    if not resolved.exists():
        return f"{target} does not exist"
    if not fragment:
        return None
    if resolved.is_dir() or resolved.suffix != ".md":
        return f"{target} has an anchor on a file that is not Markdown"
    if unquote(fragment).lower() not in anchors(resolved):
        return f"{target}: no heading or anchor #{fragment} in {resolved.name}"
    return None


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ROOTS:
        entry = root / name
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir():
            files.extend(sorted(entry.rglob("*.md")))
    return files


def _unindexed(root: Path) -> list[str]:
    index = root / GUIDE_INDEX
    if not index.is_file():
        return [f"{GUIDE_INDEX.as_posix()} is missing"]
    linked = {
        (index.parent / link.target.partition("#")[0]).resolve()
        for link in links(index)
        if not _SCHEME.match(link.target)
    }
    return [
        f"{page.relative_to(root).as_posix()} is not linked from {GUIDE_INDEX.as_posix()}"
        for page in sorted((root / GUIDE).glob("*.md"))
        if page != index and page.resolve() not in linked
    ]


def check(root: Path) -> Report:
    files = markdown_files(root)
    if not files:
        # A guard that checked nothing must not pass (CONTRIBUTING.md §6).
        return Report([f"no Markdown found under {', '.join(ROOTS)}"], 0, 0)
    failures: list[str] = []
    count = 0
    for path in files:
        for link in links(path):
            count += 1
            problem = _problem(link, root)
            if problem:
                failures.append(f"{path.relative_to(root).as_posix()}:{link.line}: {problem}")
    failures.extend(_unindexed(root))
    return Report(failures, len(files), count)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    report = check(args.root)
    for line in report.failures:
        print(f"error: {line}")
    print(
        f"doc_links: {report.checked_links} links in {report.checked_files} files checked, "
        f"{len(report.failures)} problems"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
