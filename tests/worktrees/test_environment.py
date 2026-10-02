import subprocess
from pathlib import Path

import pytest

from labhq.worktrees.environment import DROPPED_VARIABLES, worker_environment
from labhq.worktrees.git import GitError

BASE = {
    **dict.fromkeys(DROPPED_VARIABLES, "secret"),
    "GIT_CONFIG_KEY_0": "credential.helper",
    "GIT_CONFIG_VALUE_0": "store",
    "GIT_CONFIG_KEY_7": "remote.origin.pushurl",
    "GIT_CONFIG_VALUE_7": "https://example.invalid/repo.git",
    "ANTHROPIC_API_KEY": "kept-for-the-child",
    "PATH": "/usr/bin",
    "LANG": "C.UTF-8",
}


def test_the_worker_environment_contains_none_of_the_dropped_variables() -> None:
    env = worker_environment(BASE)

    assert DROPPED_VARIABLES.isdisjoint(env.keys() - {"GIT_CONFIG_COUNT"})
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert "GIT_CONFIG_KEY_7" not in env
    assert "GIT_CONFIG_VALUE_7" not in env


def test_the_list_covers_the_issue_minimum() -> None:
    required = {"GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "GIT_ASKPASS"}

    assert required <= DROPPED_VARIABLES


def test_ordinary_variables_and_the_api_key_pass_through() -> None:
    env = worker_environment(BASE)

    assert env["PATH"] == "/usr/bin"
    assert env["LANG"] == "C.UTF-8"
    assert env["ANTHROPIC_API_KEY"] == "kept-for-the-child"


def test_git_prompts_are_off_and_the_credential_helper_is_cleared() -> None:
    env = worker_environment({})

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_0"] == ""


def test_the_base_mapping_is_not_modified() -> None:
    base = dict(BASE)

    worker_environment(base)

    assert base == BASE


def test_a_global_credential_helper_never_answers_in_the_worker_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "gitconfig"
    config.write_text(
        '[credential]\n\thelper = "!f() { echo username=u; echo password=leaked; }; f"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    request = "protocol=https\nhost=example.invalid\n\n"

    assert "password=leaked" in _credential_fill(tmp_path, request, env=None)
    with pytest.raises(GitError):
        _credential_fill(tmp_path, request, env=worker_environment())


def _credential_fill(cwd: Path, request: str, env: dict[str, str] | None) -> str:
    result = subprocess.run(
        ["git", "credential", "fill"],
        cwd=cwd,
        env=env,
        input=request,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(("credential", "fill"), result.returncode, result.stderr)
    return result.stdout
