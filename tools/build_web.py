"""Hatch build hook: the built web UI travels inside the wheel as `labhq/web/` (#68).

Building the wheel runs `npm ci` and `npm run build` in `web/` and packages `web/dist`, so
`uvx labhq` serves the UI with no extra step. The hook never produces a wheel without the UI
silently: a missing `npm` or a failed build stops the build. `LABHQ_SKIP_WEB_BUILD=1` is the
one way to build a Python-only wheel, and it marks the wheel's metadata so `labhq serve` can
say why the UI is absent. Editable installs (`uv sync`) never build the UI; a checkout serves
whatever `npm run build` left in `web/dist`.

`python -m tools.build_web check-wheel PATH` and `check-sdist PATH` inspect built artefacts;
CI runs them on what `uv build` produced.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ModuleNotFoundError:  # The tests import the functions below without hatchling.
    BuildHookInterface = object  # type: ignore[assignment,misc]

SKIP_ENV = "LABHQ_SKIP_WEB_BUILD"
SKIP_VALUES = frozenset({"1", "true", "yes"})
WEB_DIR = "web"
PACKAGE_DIR = "labhq/web"
# Under `<name>.dist-info/extra_metadata/`; `labhq.api.settings` reads it by this name.
UI_ABSENT_MARKER = "web-ui-absent"
UI_ABSENT_TEXT = f"built with {SKIP_ENV}=1\n"
NPM_STEPS: tuple[tuple[str, ...], ...] = (("ci",), ("run", "build"))
# Sources only: dependencies and build output are recreated by the build from the sdist.
SDIST_FORBIDDEN = ("web/node_modules/", "web/dist/")
SDIST_REQUIRED = ("web/package.json", "web/package-lock.json", "web/index.html")

Runner = Callable[..., subprocess.CompletedProcess[Any]]


class WebBuildError(RuntimeError):
    """The web UI could not be built, so no wheel is produced."""


def skip_requested(environ: Mapping[str, str]) -> bool:
    return environ.get(SKIP_ENV, "").strip().lower() in SKIP_VALUES


def build_ui(
    web: Path,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Runner = subprocess.run,
) -> Path:
    """Run the npm build in `web` and return the directory that goes into the wheel."""
    npm = which("npm")
    if npm is None:
        raise WebBuildError(
            "npm was not found on PATH, and the labhq wheel must contain the built web UI. "
            f"Install Node.js 22.18 or later, or set {SKIP_ENV}=1 for a Python-only "
            "development build without the UI."
        )
    if not (web / "package.json").is_file():
        raise WebBuildError(f"no web UI sources at {web}: package.json is missing")
    for step in NPM_STEPS:
        command = ["npm", *step]
        if run([npm, *step], cwd=web, check=False).returncode != 0:
            raise WebBuildError(f"`{' '.join(command)}` failed in {web}; see its output above")
    dist = web / "dist"
    if not (dist / "index.html").is_file():
        raise WebBuildError(f"`npm run build` left no {dist / 'index.html'}")
    return dist


def write_ui_absent_marker(directory: Path) -> Path:
    marker = directory / UI_ABSENT_MARKER
    marker.write_text(UI_ABSENT_TEXT, encoding="utf-8")
    return marker


def prepare_wheel(
    root: Path,
    version: str,
    build_data: dict[str, Any],
    *,
    environ: Mapping[str, str],
    scratch: Callable[[], Path],
    build: Callable[[Path], Path] = build_ui,
) -> None:
    """Fill `build_data` for a wheel: the UI as package data, or the marker that it is absent."""
    # An editable install points at the checkout, which serves `web/dist` directly.
    if version == "editable":
        return
    if skip_requested(environ):
        marker = write_ui_absent_marker(scratch())
        build_data["extra_metadata"][str(marker)] = UI_ABSENT_MARKER
        return
    dist = build(root / WEB_DIR)
    build_data["force_include"][str(dist)] = PACKAGE_DIR


class WebUiBuildHook(BuildHookInterface):  # type: ignore[misc,valid-type]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        self._scratch: Path | None = None
        if self.target_name != "wheel":
            return
        prepare_wheel(
            Path(self.root), version, build_data, environ=os.environ, scratch=self._make_scratch
        )

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)

    def _make_scratch(self) -> Path:
        self._scratch = Path(tempfile.mkdtemp(prefix="labhq-web-"))
        return self._scratch


def wheel_problems(names: Iterable[str]) -> list[str]:
    """What is wrong with a wheel that must carry the UI, from its member names."""
    members = set(names)
    problems = []
    if f"{PACKAGE_DIR}/index.html" not in members:
        problems.append(f"no {PACKAGE_DIR}/index.html")
    if not any(name.startswith(f"{PACKAGE_DIR}/assets/") for name in members):
        problems.append(f"no assets under {PACKAGE_DIR}/assets/")
    if any(name.endswith(f"/extra_metadata/{UI_ABSENT_MARKER}") for name in members):
        problems.append("the metadata says the UI is absent")
    return problems


def sdist_problems(names: Iterable[str]) -> list[str]:
    """What is wrong with an sdist that must build a wheel with the UI."""
    # Members sit under `<name>-<version>/`; drop that first component.
    members = {name.partition("/")[2] for name in names}
    problems = [f"no {path}" for path in SDIST_REQUIRED if path not in members]
    for prefix in SDIST_FORBIDDEN:
        if any(member.startswith(prefix) for member in members):
            problems.append(f"it carries {prefix}")
    return problems


def wheel_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as wheel:
        return wheel.namelist()


def sdist_names(path: Path) -> list[str]:
    with tarfile.open(path) as sdist:
        return sdist.getnames()


CHECKS: dict[str, tuple[Callable[[Path], list[str]], Callable[[Iterable[str]], list[str]]]] = {
    "check-wheel": (wheel_names, wheel_problems),
    "check-sdist": (sdist_names, sdist_problems),
}


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[0] not in CHECKS:
        print(f"usage: python -m tools.build_web {{{','.join(CHECKS)}}} PATH", file=sys.stderr)
        return 2
    read, judge = CHECKS[argv[0]]
    path = Path(argv[1])
    problems = judge(read(path))
    for problem in problems:
        print(f"{path.name}: {problem}", file=sys.stderr)
    if not problems:
        print(f"{path.name}: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
