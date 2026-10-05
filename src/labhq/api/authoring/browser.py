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


@router.get("/repository-browser/suggest")
def repository_browser_suggest(
    request: Request, query: str = Query(min_length=2, max_length=4096)
) -> list[BrowserFolder]:
    """Find a few visible server folders by name or partial path for project entry."""
    needle = query.strip().casefold()
    if len(needle) < 2:
        return []
    roots = _roots(request)
    if query.startswith("/"):
        typed = Path(query)
        parent = typed if query.endswith("/") else typed.parent
        prefix = "" if query.endswith("/") else typed.name.casefold()
        root = _within_root(parent, roots)
        if root is None or any(part.startswith(".") for part in parent.relative_to(root).parts):
            return []
        try:
            if parent.is_symlink() or parent.resolve(strict=True) != parent:
                return []
            return [
                BrowserFolder(name=child.name, path=str(child))
                for child in sorted(parent.iterdir(), key=lambda path: path.name.casefold())
                if child.name.casefold().startswith(prefix)
                and not child.name.startswith(".")
                and not child.is_symlink()
                and child.is_dir()
            ][:12]
        except (OSError, RuntimeError):
            return []
    found: list[BrowserFolder] = []
    visited = 0
    stack = [(root, 0) for root in reversed(roots)]
    while stack and visited < 2000 and len(found) < 12:
        directory, depth = stack.pop()
        visited += 1
        if needle in directory.name.casefold() or needle in str(directory).casefold():
            found.append(BrowserFolder(name=directory.name, path=str(directory)))
        if depth >= 4:
            continue
        try:
            children = sorted(
                (
                    child
                    for child in directory.iterdir()
                    if not child.name.startswith(".") and not child.is_symlink() and child.is_dir()
                ),
                key=lambda child: child.name.casefold(),
            )
        except OSError:
            continue
        stack.extend((child, depth + 1) for child in reversed(children))
    return found


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
