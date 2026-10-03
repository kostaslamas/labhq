from pathlib import Path

import pytest

from tools import readme_check

REPO_ROOT = Path(__file__).resolve().parents[2]

README = """\
# labhq

<!-- ![demo](docs/media/demo.gif) -->

## Install

```sh
uvx labhq onboard
```

```sh
cp .env.example .env     # then set PROJECTS_DIR
docker compose up -d
```

## Quickstart

Run it.

## Models and billing

- Your Claude subscription login is the default. See
  [legal](https://code.claude.com/docs/en/legal-and-compliance) and
  [SDK](https://code.claude.com/docs/en/agent-sdk/overview).
- An Anthropic API key is the alternative: set `ANTHROPIC_API_KEY`.

## Security

[Security](docs/guide/security.md), and report through [SECURITY.md](SECURITY.md).
"""

WORKFLOWS = {
    ".github/workflows/onboard.yml": 'run: uvx --offline --from "${wheel}" labhq onboard\n',
    ".github/workflows/docker.yml": (
        "run: |\n  sed -e x .env.example > .env\n  docker compose up --wait\n"
    ),
    ".github/workflows/docs.yml": 'run: uv tool install "${wheel}"\n',
}


def _tree(root: Path, readme: str = README, files: dict[str, str] | None = None) -> Path:
    for name, text in {"README.md": readme, **WORKFLOWS, **(files or {})}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "docs" / "guide").mkdir(parents=True, exist_ok=True)
    return root


def test_the_repository_passes() -> None:
    assert readme_check.check(REPO_ROOT) == []


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    assert readme_check.check(_tree(tmp_path)) == []


@pytest.mark.parametrize("section", readme_check.REQUIRED_SECTIONS)
def test_every_required_section_must_exist(tmp_path: Path, section: str) -> None:
    readme = README.replace(f"## {section}\n", "## Something else\n")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert f"the README has no `## {section}` section" in failures


def test_an_install_command_no_ci_job_runs_fails(tmp_path: Path) -> None:
    readme = README.replace("uvx labhq onboard\n", "uvx labhq onboard\npipx install labhq\n")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert failures == ["install command `pipx install labhq` is run by no CI job listed here"]


def test_a_workflow_that_stopped_running_the_command_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path, files={".github/workflows/docker.yml": "# docker compose up\n"})
    failures = readme_check.check(root)
    assert "`docker compose up -d`: .github/workflows/docker.yml no longer runs it" in failures


def test_the_primary_install_command_is_required(tmp_path: Path) -> None:
    readme = README.replace("uvx labhq onboard\n", "")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert "the Install section does not show `uvx labhq onboard`" in failures


def test_the_demo_slot_stays_commented_until_the_gif_exists(tmp_path: Path) -> None:
    active = README.replace("<!-- ![demo](docs/media/demo.gif) -->", "![demo](docs/media/demo.gif)")
    assert any("does not exist yet" in f for f in readme_check.check(_tree(tmp_path, active)))

    gone = README.replace("<!-- ![demo](docs/media/demo.gif) -->", "")
    assert any("no commented-out slot" in f for f in readme_check.check(_tree(tmp_path, gone)))


def test_the_demo_slot_is_shown_once_the_gif_exists(tmp_path: Path) -> None:
    root = _tree(tmp_path, files={"docs/media/demo.gif": "GIF89a"})
    assert any("uncomment its slot" in f for f in readme_check.check(root))
    active = README.replace("<!-- ![demo](docs/media/demo.gif) -->", "![demo](docs/media/demo.gif)")
    assert readme_check.check(_tree(tmp_path, active)) == []


@pytest.mark.parametrize("url", readme_check.BILLING_LINKS)
def test_billing_links_both_anthropic_pages(tmp_path: Path, url: str) -> None:
    failures = readme_check.check(_tree(tmp_path, README.replace(url, "https://example.invalid")))
    assert f"the billing text does not link {url}" in failures


def test_billing_names_the_subscription_as_the_default(tmp_path: Path) -> None:
    readme = README.replace("login is the default", "login works")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert failures == ["the billing text does not name the subscription login as the default"]


def test_billing_names_the_api_key_as_the_alternative(tmp_path: Path) -> None:
    readme = README.replace("API key is the alternative", "API key works too")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert failures == ["the billing text does not name an API key as the alternative"]


@pytest.mark.parametrize("phrase", ["cheaper", "No extra cost", "avoid API costs"])
def test_wording_that_sells_the_subscription_fails(tmp_path: Path, phrase: str) -> None:
    root = _tree(tmp_path, files={"docs/guide/page.md": f"A plan is {phrase} than a key.\n"})
    failures = readme_check.check(root)
    assert len(failures) == 1
    assert failures[0].startswith("docs/guide/page.md: billing wording ADR 0001 rules out")


def test_the_security_section_links_the_guide_and_the_policy(tmp_path: Path) -> None:
    readme = README.replace("[SECURITY.md](SECURITY.md)", "the maintainer")
    failures = readme_check.check(_tree(tmp_path, readme))
    assert failures == ["the Security section does not link SECURITY.md"]


def test_main_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert readme_check.main(["--root", str(tmp_path)]) == 1
    assert "README.md is missing" in capsys.readouterr().out
