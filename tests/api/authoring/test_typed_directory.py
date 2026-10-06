"""Typed paths split the same way for Windows and POSIX spellings (no Windows host needed)."""

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from labhq.api.authoring.browser import typed_directory


@pytest.mark.parametrize(
    ("query", "folder", "prefix"),
    [
        ("C:\\Users\\me\\Developer\\lab", "C:\\Users\\me\\Developer", "lab"),
        ("C:\\Users\\me\\Developer\\", "C:\\Users\\me\\Developer", ""),
        ("C:/Users/me/Developer/", "C:\\Users\\me\\Developer", ""),
        ("d:\\Work\\LabHQ", "d:\\Work", "labhq"),
        ("C:\\", "C:\\", ""),
    ],
)
def test_windows_drive_paths_are_typed_paths(query: str, folder: str, prefix: str) -> None:
    assert typed_directory(query, PureWindowsPath) == (PureWindowsPath(folder), prefix)


@pytest.mark.parametrize("query", ["labhq", "C:labhq", "Developer\\labhq", "\\labhq"])
def test_relative_or_driveless_windows_text_is_a_name_search(query: str) -> None:
    assert typed_directory(query, PureWindowsPath) is None


def test_posix_paths_keep_their_behaviour() -> None:
    assert typed_directory("/srv/Dev/lab", PurePosixPath) == (PurePosixPath("/srv/Dev"), "lab")
    assert typed_directory("/srv/Dev/", PurePosixPath) == (PurePosixPath("/srv/Dev"), "")
    assert typed_directory("srv/Dev", PurePosixPath) is None


def test_a_backslash_is_not_a_separator_on_posix() -> None:
    assert typed_directory("/srv/a\\", PurePosixPath) == (PurePosixPath("/srv"), "a\\")
