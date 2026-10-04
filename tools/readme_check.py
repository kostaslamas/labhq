"""README guard (issue #80): the launch sections exist, every install command is one a CI job
runs, the demo GIF slot matches the file, and the billing text follows ADR 0001.

The tables below are the policy. A new install command in the README needs a row in
`INSTALL_COMMANDS` naming the workflow that runs it; a row whose workflow no longer runs the
command fails, so the two cannot drift apart silently.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

README = Path("README.md")
GUIDE = Path("docs/guide")
DEMO_GIF = "docs/media/demo.gif"

REQUIRED_SECTIONS = ("Install", "Quickstart", "Models and billing", "Security")
INSTALL_SECTION = "Install"
BILLING_SECTION = "Models and billing"
SECURITY_PAGE = "docs/guide/security.md"
REPORTING_PAGE = "SECURITY.md"


@dataclass(frozen=True)
class CiRun:
    workflow: str
    # Matched against the workflow's lines without comments: the job's own form of the command.
    pattern: str


# The command as the README shows it -> the CI step that runs it.
INSTALL_COMMANDS: dict[str, CiRun] = {
    # #53: the built wheel through uvx on fresh Linux and macOS runners.
    "uvx labhq onboard": CiRun(".github/workflows/onboard.yml", r"\buvx\b.*\blabhq onboard\b"),
    # This issue's docs workflow installs the built wheel as a uv tool and runs it.
    "uv tool install labhq": CiRun(".github/workflows/docs.yml", r"\buv tool install\b"),
    # #69: .env from .env.example, then compose up until healthy.
    "cp .env.example .env": CiRun(".github/workflows/docker.yml", r"\.env\.example > \.env\b"),
    "docker compose up -d": CiRun(".github/workflows/docker.yml", r"\bdocker compose up\b"),
    # #131: the same stack under rootless Podman, through the overlay.
    "podman compose -f compose.yaml -f compose.podman.yaml up -d": CiRun(
        ".github/workflows/docker.yml", r"\bpodman compose up\b"
    ),
}
PRIMARY_INSTALL_COMMAND = "uvx labhq onboard"

# ADR 0001: both pages the decision quotes are linked from the billing text.
BILLING_LINKS = (
    "https://code.claude.com/docs/en/legal-and-compliance",
    "https://code.claude.com/docs/en/agent-sdk/overview",
)
# ADR 0001: no wording that sells subscription use as a way to avoid API costs. Matched
# case-insensitively in the README and every guide page.
FORBIDDEN_BILLING_PHRASES = (
    "cheaper",
    "save money",
    "saves money",
    "saving money",
    "save on api",
    "avoid api cost",
    "avoid the api cost",
    "avoid paying",
    "without paying",
    "instead of paying",
    "no extra cost",
    "no additional cost",
    "at no cost",
    "costs nothing",
    "for free",
    "free of charge",
    "no api bill",
    "skip the api",
    "unlimited usage",
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def sections(text: str) -> dict[str, str]:
    """`## Title` -> its body, up to the next heading of level two or higher."""
    found: dict[str, str] = {}
    matches = [match for match in _HEADING.finditer(text) if len(match.group(1)) == 2]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(2)] = text[match.end() : end]
    return found


def install_commands(section: str) -> list[str]:
    commands: list[str] = []
    for block in _FENCE.findall(section):
        for line in block.splitlines():
            command = line.split(" #", 1)[0].strip()
            if command and not command.startswith("#"):
                commands.append(command)
    return commands


def _workflow_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


def _check_install(text: str, root: Path) -> list[str]:
    section = sections(text).get(INSTALL_SECTION, "")
    commands = install_commands(section)
    if PRIMARY_INSTALL_COMMAND not in commands:
        return [f"the {INSTALL_SECTION} section does not show `{PRIMARY_INSTALL_COMMAND}`"]
    failures: list[str] = []
    for command in commands:
        run = INSTALL_COMMANDS.get(command)
        if run is None:
            failures.append(f"install command `{command}` is run by no CI job listed here")
            continue
        workflow = root / run.workflow
        if not workflow.is_file():
            failures.append(f"`{command}`: {run.workflow} does not exist")
        elif not any(re.search(run.pattern, line) for line in _workflow_lines(workflow)):
            failures.append(f"`{command}`: {run.workflow} no longer runs it")
    return failures


def _check_demo_slot(text: str, root: Path) -> list[str]:
    commented = any(DEMO_GIF in comment for comment in _COMMENT.findall(text))
    active = DEMO_GIF in _COMMENT.sub("", text)
    if (root / DEMO_GIF).is_file():
        return [] if active else [f"{DEMO_GIF} exists; uncomment its slot in the README"]
    if active:
        return [f"the README shows {DEMO_GIF}, which does not exist yet; comment the slot out"]
    return [] if commented else [f"the README has no commented-out slot for {DEMO_GIF}"]


def _sentences(text: str) -> list[str]:
    return _SENTENCE_END.split(" ".join(text.split()))


def _check_billing(text: str) -> list[str]:
    section = sections(text).get(BILLING_SECTION, "")
    failures = [
        f"the billing text does not link {url}" for url in BILLING_LINKS if url not in section
    ]
    sentences = [sentence.lower() for sentence in _sentences(section)]
    if not any("subscription" in s and "is the default" in s for s in sentences):
        failures.append("the billing text does not name the subscription login as the default")
    if not any("api key is the alternative" in s for s in sentences):
        failures.append("the billing text does not name an API key as the alternative")
    if "ANTHROPIC_API_KEY" not in section:
        failures.append("the billing text does not name ANTHROPIC_API_KEY")
    return failures


def _check_phrases(root: Path) -> list[str]:
    pages = [root / README, *sorted((root / GUIDE).glob("*.md"))]
    failures: list[str] = []
    for page in pages:
        lowered = " ".join(page.read_text(encoding="utf-8").lower().split())
        failures.extend(
            f"{page.relative_to(root).as_posix()}: billing wording ADR 0001 rules out: {phrase!r}"
            for phrase in FORBIDDEN_BILLING_PHRASES
            if phrase in lowered
        )
    return failures


def check(root: Path) -> list[str]:
    readme = root / README
    if not readme.is_file():
        return [f"{README} is missing"]
    text = readme.read_text(encoding="utf-8")
    present = sections(text)
    failures = [
        f"the README has no `## {name}` section"
        for name in REQUIRED_SECTIONS
        if name not in present
    ]
    security = present.get("Security", "")
    for page in (SECURITY_PAGE, REPORTING_PAGE):
        if page not in security:
            failures.append(f"the Security section does not link {page}")
    failures += _check_install(text, root)
    failures += _check_demo_slot(text, root)
    failures += _check_billing(text)
    failures += _check_phrases(root)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    failures = check(args.root)
    for line in failures:
        print(f"error: {line}")
    print(f"readme_check: {len(failures)} problems")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
