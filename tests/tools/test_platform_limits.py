"""Native Windows limitations: the marker plugin's guards and the guide generated from it."""

import os
from pathlib import Path

import pytest

import tests.platforms as platforms
from tools.platform_limits import (
    END,
    GUIDE,
    START,
    Limitation,
    MarkerError,
    limitations,
    main,
    render,
)

pytest_plugins = ["pytester"]

REPO_ROOT = Path(__file__).resolve().parents[2]
# The inner sessions need the plugin under test and nothing that warns about its own config.
PLUGINS = ("-p", "tests.platforms", "-p", "no:asyncio")


def run_suite(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, windows: bool, source: str
) -> pytest.RunResult:
    monkeypatch.setattr(platforms, "on_native_windows", lambda: windows)
    pytester.makepyfile(test_sample=source)
    return pytester.runpytest_inprocess(*PLUGINS)


FAILS = '@pytest.mark.posix_only("no fork")\ndef test_it():\n    assert False\n'
PASSES = '@pytest.mark.posix_only("no fork")\ndef test_it():\n    pass\n'


def test_a_limitation_is_a_strict_xfail_on_native_windows(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_suite(pytester, monkeypatch, True, "import pytest\n" + FAILS)
    result.assert_outcomes(xfailed=1)
    assert result.ret == pytest.ExitCode.OK


def test_a_limitation_that_passes_on_native_windows_fails_the_job(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_suite(pytester, monkeypatch, True, "import pytest\n" + PASSES)
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*XPASS(strict)*native Windows: no fork*"])


def test_off_windows_a_limitation_has_no_effect(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_suite(pytester, monkeypatch, False, "import pytest\n" + FAILS)
    result.assert_outcomes(failed=1)


@pytest.mark.parametrize(
    "mark", ["pytest.mark.posix_only", "pytest.mark.posix_only('')", "pytest.mark.posix_only(1)"]
)
def test_a_limitation_needs_a_reason(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, mark: str
) -> None:
    result = run_suite(
        pytester, monkeypatch, True, f"import pytest\n@{mark}\ndef test_it(): pass\n"
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR


@pytest.mark.parametrize(
    "skip",
    [
        "@pytest.mark.skip(reason='later')\ndef test_it(): pass\n",
        "@pytest.mark.skipif(True, reason='later')\ndef test_it(): pass\n",
        "def test_it():\n    pytest.skip('later')\n",
    ],
)
def test_a_skipped_test_fails_the_session(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, skip: str
) -> None:
    result = run_suite(pytester, monkeypatch, False, "import pytest\n" + skip)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*skipped tests are not allowed*", "*test_sample.py::test_it"])


@pytest.mark.parametrize("windows", [True, False])
def test_windows_test_files_are_collected_on_windows_alone(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(platforms, "on_native_windows", lambda: windows)
    pytester.makepyfile(test_taskkill_windows="def test_it(): pass\n")
    result = pytester.runpytest_inprocess(*PLUGINS)
    result.assert_outcomes(passed=1 if windows else 0)


def test_limitations_are_in_effect_on_native_windows_only(request: pytest.FixtureRequest) -> None:
    # The guard for Linux and macOS: no limitation mark may turn into an xfail there.
    marked = [i.nodeid for i in request.session.items if i.get_closest_marker("posix_only")]
    xfails = [i.nodeid for i in request.session.items if i.get_closest_marker("xfail")]
    expected = marked if os.name == "nt" else []
    assert request.config.stash[platforms.APPLIED] == expected
    assert xfails == expected


def write_tests(root: Path, files: dict[str, str]) -> None:
    for name, source in files.items():
        path = root / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_limitations_are_read_from_every_kind_of_marker(tmp_path: Path) -> None:
    write_tests(
        tmp_path,
        {
            "a/test_module.py": "import pytest\npytestmark = pytest.mark.posix_only('tmux')\n",
            "test_scopes.py": (
                "import pytest\nfrom pytest import mark\n\n"
                "class TestShell:\n"
                "    @pytest.mark.posix_only('POSIX   shell\\n parsing')\n"
                "    async def test_quotes(self): ...\n\n"
                "@mark.posix_only('process groups')\n"
                "def test_group(): ...\n\n"
                "def test_plain(): ...\n"
            ),
        },
    )
    assert limitations(tmp_path) == [
        Limitation("tests/a/test_module.py", "tmux"),
        Limitation("tests/test_scopes.py::TestShell::test_quotes", "POSIX shell parsing"),
        Limitation("tests/test_scopes.py::test_group", "process groups"),
    ]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("@pytest.mark.posix_only\ndef test_it(): ...\n", "needs a reason"),
        ("@pytest.mark.posix_only(REASON)\ndef test_it(): ...\n", "string literal"),
        ("@pytest.mark.posix_only(' ')\ndef test_it(): ...\n", "is empty"),
        ("@pytest.mark.posix_only('a', 'b')\ndef test_it(): ...\n", "exactly one reason"),
        ("limit = pytest.mark.posix_only('a')\n", "on a test or in `pytestmark`"),
    ],
)
def test_a_marker_the_guide_cannot_list_is_an_error(
    tmp_path: Path, source: str, message: str
) -> None:
    write_tests(tmp_path, {"test_bad.py": "import pytest\n" + source})
    with pytest.raises(MarkerError, match=message):
        limitations(tmp_path)


def make_guide(root: Path, block: str) -> Path:
    guide = root / GUIDE
    guide.parent.mkdir(parents=True, exist_ok=True)
    guide.write_text(f"# Platforms\n\n{block}\n\nMore prose.\n", encoding="utf-8")
    return guide


def test_write_regenerates_the_table_and_check_then_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_tests(
        tmp_path, {"test_x.py": "import pytest\npytestmark = pytest.mark.posix_only('x')\n"}
    )
    guide = make_guide(tmp_path, f"{START}\nstale\n{END}")
    assert main(["--root", str(tmp_path)]) == 1
    assert "does not match" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "--write"]) == 0
    assert "| `tests/test_x.py` | x |" in guide.read_text(encoding="utf-8")
    assert guide.read_text(encoding="utf-8").endswith("More prose.\n")
    assert main(["--root", str(tmp_path)]) == 0


def test_a_guide_without_the_generated_block_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_tests(tmp_path, {})
    make_guide(tmp_path, "no block")
    assert main(["--root", str(tmp_path)]) == 1
    assert "no generated block" in capsys.readouterr().out


def test_no_limitation_renders_an_explicit_empty_table() -> None:
    assert "| (none) | |" in render([])


def test_the_repository_guide_matches_the_markers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(REPO_ROOT)]) == 0, capsys.readouterr().out
