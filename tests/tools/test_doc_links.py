from pathlib import Path

import pytest

from tools import doc_links

REPO_ROOT = Path(__file__).resolve().parents[2]

INDEX = "# Guide\n\n- [Setup](setup.md)\n"
SETUP = "# Setup\n\n## Install `uv`\n\n## Notes\n\n## Notes\n"


def _tree(root: Path, files: dict[str, str]) -> Path:
    base = {"README.md": "# Project\n", "docs/guide/index.md": INDEX, "docs/guide/setup.md": SETUP}
    for name, text in {**base, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _failures(root: Path) -> list[str]:
    return doc_links.check(root).failures


def test_the_repository_passes() -> None:
    report = doc_links.check(REPO_ROOT)
    assert report.failures == []
    assert report.checked_links > 0


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    readme = (
        "See [setup](docs/guide/setup.md#install-uv) and [notes](docs/guide/setup.md#notes-1).\n"
    )
    assert _failures(_tree(tmp_path, {"README.md": readme})) == []


def test_a_missing_file_fails(tmp_path: Path) -> None:
    failures = _failures(_tree(tmp_path, {"README.md": "[gone](docs/gone.md)\n"}))
    assert failures == ["README.md:1: docs/gone.md does not exist"]


def test_a_missing_anchor_fails(tmp_path: Path) -> None:
    failures = _failures(_tree(tmp_path, {"README.md": "[x](docs/guide/setup.md#nowhere)\n"}))
    assert len(failures) == 1
    assert "no heading or anchor #nowhere" in failures[0]


def test_a_same_page_anchor_is_checked(tmp_path: Path) -> None:
    readme = "# Project\n\n## Quick start\n\n[ok](#quick-start) [bad](#quickstart)\n"
    failures = _failures(_tree(tmp_path, {"README.md": readme}))
    assert len(failures) == 1
    assert "#quickstart" in failures[0]


def test_reference_links_and_html_links_are_checked(tmp_path: Path) -> None:
    readme = '[a][ref]\n\n[ref]: docs/missing.md\n\n<img src="docs/media/demo.gif">\n'
    failures = _failures(_tree(tmp_path, {"README.md": readme}))
    assert any("docs/missing.md" in line for line in failures)
    assert any("docs/media/demo.gif" in line for line in failures)


def test_links_in_code_and_comments_are_not_links(tmp_path: Path) -> None:
    readme = (
        "```md\n[x](nowhere.md)\n```\n\n"
        "`[y](nowhere.md)`\n\n"
        "<!-- ![demo](docs/media/demo.gif)\n-->\n"
    )
    assert _failures(_tree(tmp_path, {"README.md": readme})) == []


def test_external_links_are_not_fetched(tmp_path: Path) -> None:
    readme = "[a](https://example.invalid/x) [b](mailto:someone@example.invalid)\n"
    assert _failures(_tree(tmp_path, {"README.md": readme})) == []


def test_a_link_outside_the_repository_fails(tmp_path: Path) -> None:
    failures = _failures(_tree(tmp_path / "repo", {"README.md": "[x](../outside.md)\n"}))
    assert failures == ["README.md:1: ../outside.md points outside the repository"]


def test_a_guide_page_missing_from_the_index_fails(tmp_path: Path) -> None:
    failures = _failures(_tree(tmp_path, {"docs/guide/extra.md": "# Extra\n"}))
    assert failures == ["docs/guide/extra.md is not linked from docs/guide/index.md"]


def test_a_missing_index_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path, {})
    (root / "docs/guide/index.md").unlink()
    assert "docs/guide/index.md is missing" in _failures(root)


def test_nothing_to_check_fails(tmp_path: Path) -> None:
    assert doc_links.main(["--root", str(tmp_path)]) == 1


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("Install `uv`", "install-uv"),
        ("`labhq.notify.settings.NotifySettings`", "labhqnotifysettingsnotifysettings"),
        ("What labhq is, and is not", "what-labhq-is-and-is-not"),
        (
            "Why your own domain behind corporate networks",
            "why-your-own-domain-behind-corporate-networks",
        ),
        ("[Link](x.md) and **bold**", "link-and-bold"),
    ],
)
def test_slugs_follow_github(heading: str, anchor: str) -> None:
    assert doc_links.slug(heading) == anchor
