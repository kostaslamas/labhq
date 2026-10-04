"""Signed-in directory picker for projects on the machine running labhq."""

from pathlib import Path

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from labhq.api.errors import ApiError

router = APIRouter(tags=["authoring"])


class BrowserFolder(BaseModel):
    name: str
    path: str


class BrowserListing(BaseModel):
    roots: list[BrowserFolder]
    path: str | None
    parent: str | None
    folders: list[BrowserFolder]


def _roots(request: Request) -> list[Path]:
    roots = []
    for configured in request.app.state.settings.repository_browser_roots:
        root = configured.expanduser().resolve()
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def _within_root(path: Path, roots: list[Path]) -> Path | None:
    return next((root for root in roots if path == root or root in path.parents), None)


@router.get("/repository-browser")
def repository_browser_get(
    request: Request, path: str | None = Query(default=None, max_length=4096)
) -> BrowserListing:
    """List visible directories only; the create route validates the chosen folder."""
    roots = _roots(request)
    choices = [BrowserFolder(name=root.name or str(root), path=str(root)) for root in roots]
    if path is None:
        return BrowserListing(roots=choices, path=None, parent=None, folders=[])

    requested = Path(path)
    if not requested.is_absolute():
        raise ApiError(422, "browser_path_not_absolute", "Give a full directory path.")
    if _within_root(requested, roots) is None:
        raise ApiError(403, "browser_path_outside_roots", "That directory cannot be browsed.")
    try:
        directory = requested.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ApiError(404, "browser_path_missing", "That directory is not available.") from None
    root = _within_root(directory, roots)
    if root is None or any(part.startswith(".") for part in directory.relative_to(root).parts):
        raise ApiError(403, "browser_path_outside_roots", "That directory cannot be browsed.")
    if not directory.is_dir():
        raise ApiError(404, "browser_path_missing", "That directory is not available.")
    try:
        folders = sorted(
            (
                BrowserFolder(name=child.name, path=str(child.resolve()))
                for child in directory.iterdir()
                if not child.name.startswith(".") and not child.is_symlink() and child.is_dir()
            ),
            key=lambda folder: folder.name.casefold(),
        )
    except OSError:
        raise ApiError(403, "browser_path_unreadable", "That directory cannot be read.") from None
    return BrowserListing(
        roots=choices,
        path=str(directory),
        parent=str(directory.parent) if directory != root else None,
        folders=folders,
    )
