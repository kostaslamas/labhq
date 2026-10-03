"""Release tags agree with the files they ship, and the release surface is guarded."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from tools import release_check

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
TAG = "v0.5.0-beta.1"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **GIT_ENV}, check=True, capture_output=True
    )


def write_release(repo: Path, version: str = "0.5.0b1", section: str = TAG) -> None:
    (repo / "pyproject.toml").write_text(f'[project]\nname = "labhq"\nversion = "{version}"\n')
    (repo / "LICENSE").write_text("MIT\n")
    (repo / "SECURITY.md").write_text("# Security policy\n")
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## {section}\n\n- a change\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "chore(release): prepare")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--initial-branch=main")
    return tmp_path


def run(repo: Path, tag: str = TAG) -> int:
    return release_check.main([tag, "--repo", str(repo)])


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v0.5.0-beta.1", "0.5.0b1"),
        ("v0.1.0-alpha.1", "0.1.0a1"),
        ("v1.0.0-rc.2", "1.0.0rc2"),
        ("v1.2.3", "1.2.3"),
    ],
)
def test_tag_maps_to_pep440(tag: str, version: str) -> None:
    assert release_check.pep440_version(tag) == version


@pytest.mark.parametrize("tag", ["0.5.0", "v0.5.0b1", "v0.5.0-beta", "v0.0.1-spike", "v1.0"])
def test_malformed_tag_is_rejected(tag: str) -> None:
    with pytest.raises(release_check.ReleaseError):
        release_check.pep440_version(tag)


def test_annotated_tag_with_matching_files_passes(repo: Path) -> None:
    write_release(repo)
    git(repo, "tag", "-a", TAG, "-m", TAG)

    assert run(repo) == 0


def test_version_mismatch_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_release(repo, version="0.5.0a1")
    git(repo, "tag", "-a", TAG, "-m", TAG)

    assert run(repo) == 1
    assert "needs '0.5.0b1'" in capsys.readouterr().out


def test_lightweight_tag_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_release(repo)
    git(repo, "tag", TAG)

    assert run(repo) == 1
    assert "lightweight" in capsys.readouterr().out


def test_missing_tag_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_release(repo)

    assert run(repo) == 1
    assert "does not exist" in capsys.readouterr().out


def test_missing_changelog_section_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A section for an earlier tag whose name is a prefix must not count.
    write_release(repo, section="v0.5.0-beta.10")
    git(repo, "tag", "-a", TAG, "-m", TAG)

    assert run(repo) == 1
    assert "no section for v0.5.0-beta.1" in capsys.readouterr().out


def test_missing_root_file_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_release(repo)
    git(repo, "rm", "-q", "SECURITY.md")
    git(repo, "commit", "-m", "chore: drop the policy")
    git(repo, "tag", "-a", TAG, "-m", TAG)

    assert run(repo) == 1
    assert "missing at the repository root: SECURITY.md" in capsys.readouterr().out


# Guards on this repository's own release surface.


@pytest.mark.parametrize("name", release_check.ROOT_FILES)
def test_root_file_exists(name: str) -> None:
    assert (REPO_ROOT / name).is_file()


def _github_slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(markdown: Path) -> set[str]:
    text = markdown.read_text(encoding="utf-8")
    return {_github_slug(m) for m in re.findall(r"^#+ (.+)$", text, re.MULTILINE)}


def test_security_policy_covers_reporting_versions_and_scope() -> None:
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for heading in ("Supported versions", "Reporting a vulnerability", "In scope", "Out of scope"):
        assert f"\n## {heading}\n" in text
    assert "/security/advisories/new" in text
    assert "never handles Claude credentials" in text
    assert "bypassPermissions" in text


def test_security_policy_links_resolve() -> None:
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)\s]+)\)", text)
    assert links, "SECURITY.md has no links to check"
    for link in links:
        if link.startswith("https://"):
            assert link.startswith("https://github.com/kostaslamas/labhq/"), link
            continue
        path, _, anchor = link.partition("#")
        target = REPO_ROOT / path
        assert target.is_file(), f"SECURITY.md links to a missing file: {link}"
        if anchor:
            assert anchor in _anchors(target), f"SECURITY.md links to a missing anchor: {link}"


def test_release_workflow_builds_installs_and_runs_the_wheel() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m tools.release_check" in text
    assert "uv build" in text
    assert "uv pip install" in text and "dist/*.whl" in text
    assert 'labhq" --version' in text or "labhq --version" in text


def test_release_workflow_publishes_only_through_trusted_publishing() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "uv publish --trusted-publishing always" in text
    assert "id-token: write" in text
    # No stored secret of any kind: PyPI exchanges the job's OIDC token instead.
    assert "secrets." not in text
    for credential in ("password:", "UV_PUBLISH_TOKEN", "PYPI_TOKEN", "--token", "TWINE_"):
        assert credential not in text
    # Only the publish job may mint an OIDC token.
    assert text.count("id-token: write") == 1
