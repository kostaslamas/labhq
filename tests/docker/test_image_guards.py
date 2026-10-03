"""Guards on the Docker files (#69): non-root, loopback-only, no secrets, no credential paths.

The CI job (`.github/workflows/docker.yml`) proves the same on a running container; these read
the files themselves, so a change that breaks a rule fails `pytest` before anything is built.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "compose.yaml"
DOCKERIGNORE = ROOT / ".dockerignore"
GUARD = ROOT / "tools" / "guards" / "credential_refs.py"
# Every file this issue adds that a user copies, builds or reads.
DOCKER_FILES = (
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    ".env.example",
    "docs/guide/docker.md",
    "docs/checks/docker.md",
)
ROOT_USERS = frozenset({"root", "0"})
LOOPBACK = "127.0.0.1:"


def instructions(dockerfile: str) -> list[tuple[str, str]]:
    """(KEYWORD, arguments) per instruction, with continuation lines joined."""
    joined = re.sub(r"\\\n", " ", dockerfile)
    result = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keyword, _, arguments = stripped.partition(" ")
        result.append((keyword.upper(), arguments.strip()))
    return result


def final_stage(dockerfile: str) -> list[tuple[str, str]]:
    steps = instructions(dockerfile)
    starts = [index for index, (keyword, _) in enumerate(steps) if keyword == "FROM"]
    assert starts, "the Dockerfile has no FROM"
    return steps[starts[-1] :]


def arg_defaults(dockerfile: str) -> dict[str, str]:
    defaults = {}
    for keyword, arguments in instructions(dockerfile):
        name, sep, value = arguments.partition("=")
        if keyword == "ARG" and sep:
            defaults[name] = value
    return defaults


def published_ports(compose: str) -> list[str]:
    """Every entry of every `ports:` list in the compose file, unquoted."""
    entries = []
    lines = compose.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "ports:":
            continue
        indent = len(line) - len(line.lstrip())
        for item in lines[index + 1 :]:
            if not item.strip() or item.strip().startswith("#"):
                continue
            if len(item) - len(item.lstrip()) <= indent:
                break
            entries.append(item.strip().removeprefix("-").strip().strip("\"'"))
    return entries


def test_the_final_stage_runs_as_a_non_root_user() -> None:
    stage = final_stage(DOCKERFILE.read_text(encoding="utf-8"))
    users = [arguments.split(":")[0] for keyword, arguments in stage if keyword == "USER"]

    assert users, "the final stage never sets USER, so it runs as root"
    assert users[-1] not in ROOT_USERS


def test_the_image_user_ids_default_to_non_root_and_refuse_zero() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    defaults = arg_defaults(text)

    assert defaults["UID"] != "0"
    assert defaults["GID"] != "0"
    assert 'test "${UID}" != 0' in text
    assert 'test "${GID}" != 0' in text


def test_compose_publishes_on_loopback_only() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    ports = published_ports(text)

    # An empty list would pass the loop below without checking anything.
    assert ports, "compose.yaml publishes no port"
    for entry in ports:
        assert entry.startswith(LOOPBACK), f"{entry!r} is published beyond 127.0.0.1"
    assert not re.search(r"^\s*network_mode:\s*host\b", text, re.MULTILINE)
    assert not re.search(r"^\s*user:\s*[\"']?(?:root|0)\b", text, re.MULTILINE)


@pytest.mark.parametrize(
    ("compose", "expected"),
    [
        ('    ports:\n      - "8787:8787"\n', ["8787:8787"]),
        ("    ports:\n      - 0.0.0.0:80:80\n    volumes:\n      - a:/a\n", ["0.0.0.0:80:80"]),
        ("    image: x\n", []),
    ],
)
def test_the_port_reader_sees_what_a_bad_file_publishes(compose: str, expected: list[str]) -> None:
    assert published_ports(compose) == expected


def test_secrets_stay_out_of_the_build_context() -> None:
    ignored = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".env.*" in ignored
    assert ".git" in ignored


def run_guard(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def docker_files(tmp_path: Path) -> Path:
    # The guard walks directories; a copy lets it scan exactly these root-level files.
    scanned = tmp_path / "docker-files"
    for name in DOCKER_FILES:
        target = scanned / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return scanned


def test_no_credential_reference_in_the_docker_files(docker_files: Path) -> None:
    result = run_guard(docker_files)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Checked {len(DOCKER_FILES)} files" in result.stdout


def test_the_guard_catches_a_credential_path_planted_in_a_docker_file(
    docker_files: Path,
) -> None:
    compose = docker_files / "compose.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8") + "# ~/.claude/.credentials.json\n",
        encoding="utf-8",
    )

    result = run_guard(docker_files)

    assert result.returncode == 1
    assert "credentials-file" in result.stdout
