import io
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.build_web import (
    PACKAGE_DIR,
    SKIP_ENV,
    UI_ABSENT_MARKER,
    WebBuildError,
    build_ui,
    main,
    prepare_wheel,
    sdist_problems,
    skip_requested,
    wheel_names,
    wheel_problems,
)

# Set by the package workflow to the wheel `uv build` produced from the sdist.
BUILT_WHEEL = os.environ.get("LABHQ_BUILT_WHEEL")
GOOD_WHEEL = [
    "labhq/__init__.py",
    f"{PACKAGE_DIR}/index.html",
    f"{PACKAGE_DIR}/assets/index-abc.js",
    "labhq-0.1.0.dist-info/METADATA",
]
GOOD_SDIST = [
    "labhq-0.1.0/pyproject.toml",
    "labhq-0.1.0/web/package.json",
    "labhq-0.1.0/web/package-lock.json",
    "labhq-0.1.0/web/index.html",
    "labhq-0.1.0/web/src/main.ts",
]


def empty_build_data() -> dict[str, Any]:
    return {"force_include": {}, "extra_metadata": {}}


def web_sources(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    return web


def test_a_build_without_npm_fails_with_a_clear_message(tmp_path: Path) -> None:
    with pytest.raises(WebBuildError) as caught:
        build_ui(web_sources(tmp_path), which=lambda _: None)
    message = str(caught.value)
    assert "npm was not found on PATH" in message
    assert f"{SKIP_ENV}=1" in message


def test_the_build_runs_npm_ci_then_npm_run_build_in_web(tmp_path: Path) -> None:
    web = web_sources(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def run(command: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        if command[1:] == ["run", "build"]:
            (cwd / "dist").mkdir()
            (cwd / "dist" / "index.html").write_text("<!doctype html>")
        return subprocess.CompletedProcess(command, 0)

    dist = build_ui(web, which=lambda _: "/bin/npm", run=run)
    assert dist == web / "dist"
    assert calls == [(["/bin/npm", "ci"], web), (["/bin/npm", "run", "build"], web)]


def test_a_failed_npm_step_stops_the_build(tmp_path: Path) -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1)

    with pytest.raises(WebBuildError, match="`npm ci` failed"):
        build_ui(web_sources(tmp_path), which=lambda _: "/bin/npm", run=run)


def test_a_build_that_leaves_no_index_stops_the_build(tmp_path: Path) -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    with pytest.raises(WebBuildError, match="left no"):
        build_ui(web_sources(tmp_path), which=lambda _: "/bin/npm", run=run)


def test_missing_sources_stop_the_build(tmp_path: Path) -> None:
    with pytest.raises(WebBuildError, match=r"package\.json is missing"):
        build_ui(tmp_path, which=lambda _: "/bin/npm")


@pytest.mark.parametrize(
    ("value", "expected"), [("1", True), ("true", True), ("", False), ("0", False)]
)
def test_only_an_explicit_value_skips_the_ui(value: str, expected: bool) -> None:
    assert skip_requested({SKIP_ENV: value}) is expected


def test_a_wheel_packages_the_built_ui_under_labhq_web(tmp_path: Path) -> None:
    build_data = empty_build_data()
    dist = tmp_path / "web" / "dist"
    built: list[Path] = []

    def build(web: Path) -> Path:
        built.append(web)
        return dist

    prepare_wheel(tmp_path, "standard", build_data, environ={}, scratch=Path, build=build)
    assert built == [tmp_path / "web"]
    assert build_data == {"force_include": {str(dist): PACKAGE_DIR}, "extra_metadata": {}}


def test_a_skipped_build_marks_the_wheel_metadata(tmp_path: Path) -> None:
    build_data = empty_build_data()

    def build(web: Path) -> Path:
        raise AssertionError("the UI must not be built")

    prepare_wheel(
        tmp_path,
        "standard",
        build_data,
        environ={SKIP_ENV: "1"},
        scratch=lambda: tmp_path,
        build=build,
    )
    marker = tmp_path / UI_ABSENT_MARKER
    assert build_data == {"force_include": {}, "extra_metadata": {str(marker): UI_ABSENT_MARKER}}
    assert SKIP_ENV in marker.read_text()


def test_an_editable_install_never_runs_npm(tmp_path: Path) -> None:
    build_data = empty_build_data()

    def build(web: Path) -> Path:
        raise AssertionError("the UI must not be built")

    prepare_wheel(tmp_path, "editable", build_data, environ={}, scratch=Path, build=build)
    assert build_data == empty_build_data()


def test_a_wheel_check_names_what_is_missing() -> None:
    assert wheel_problems(GOOD_WHEEL) == []
    skipped = ["labhq/__init__.py", f"labhq-0.1.0.dist-info/extra_metadata/{UI_ABSENT_MARKER}"]
    assert wheel_problems(skipped) == [
        f"no {PACKAGE_DIR}/index.html",
        f"no assets under {PACKAGE_DIR}/assets/",
        "the metadata says the UI is absent",
    ]


def test_an_sdist_check_wants_sources_and_no_build_output() -> None:
    assert sdist_problems(GOOD_SDIST) == []
    polluted = [*GOOD_SDIST[1:], "labhq-0.1.0/web/node_modules/vue/index.js"]
    polluted.append("labhq-0.1.0/web/dist/index.html")
    assert sdist_problems(polluted) == ["it carries web/node_modules/", "it carries web/dist/"]
    assert sdist_problems(GOOD_SDIST[:1]) == [
        "no web/package.json",
        "no web/package-lock.json",
        "no web/index.html",
    ]


def write_wheel(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as wheel:
        for name in names:
            wheel.writestr(name, "x")
    return path


def write_sdist(path: Path, names: list[str]) -> Path:
    with tarfile.open(path, "w:gz") as sdist:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 1
            sdist.addfile(info, io.BytesIO(b"x"))
    return path


def test_the_command_line_checks_built_artefacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel = write_wheel(tmp_path / "good.whl", GOOD_WHEEL)
    assert main(["check-wheel", str(wheel)]) == 0
    assert main(["check-sdist", str(write_sdist(tmp_path / "good.tar.gz", GOOD_SDIST))]) == 0
    assert main(["check-wheel", str(write_wheel(tmp_path / "bad.whl", GOOD_WHEEL[:1]))]) == 1
    assert main(["check-wheel"]) == 2
    assert "bad.whl: no labhq/web/index.html" in capsys.readouterr().err


@pytest.mark.skipif(BUILT_WHEEL is None, reason="LABHQ_BUILT_WHEEL is set by package.yml")
def test_the_wheel_built_in_ci_contains_the_ui() -> None:
    assert BUILT_WHEEL is not None
    assert wheel_problems(wheel_names(Path(BUILT_WHEEL))) == []
