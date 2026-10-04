"""Repository picker lists only visible directories inside its configured roots."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_browse_folders_and_select_a_repository(
    signed_in: TestClient, tmp_path: Path, repo: Path
) -> None:
    signed_in.app.state.settings.repository_browser_roots = [tmp_path]
    (tmp_path / "plain").mkdir()
    (tmp_path / ".private").mkdir()
    (tmp_path / "file.txt").write_text("not a directory", encoding="utf-8")

    roots = signed_in.get("/api/repository-browser")
    assert roots.status_code == 200
    assert roots.json()["roots"] == [{"name": tmp_path.name, "path": str(tmp_path)}]

    listing = signed_in.get("/api/repository-browser", params={"path": str(tmp_path)})
    assert listing.status_code == 200
    assert listing.json()["path"] == str(tmp_path)
    assert listing.json()["parent"] is None
    names = [folder["name"] for folder in listing.json()["folders"]]
    assert "project" in names and "plain" in names
    assert ".private" not in names and "file.txt" not in names

    selected = signed_in.get("/api/repository-browser", params={"path": str(repo)})
    assert selected.status_code == 200
    assert selected.json()["path"] == str(repo)
    assert selected.json()["parent"] == str(tmp_path)


def test_browse_rejects_paths_outside_roots_and_hidden_directories(
    signed_in: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (root / ".private").mkdir()
    signed_in.app.state.settings.repository_browser_roots = [root]

    listing = signed_in.get("/api/repository-browser", params={"path": str(root)})
    assert listing.json()["folders"] == []
    for path in (secret, root / ".." / "secret", root / ".private"):
        response = signed_in.get("/api/repository-browser", params={"path": str(path)})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "browser_path_outside_roots"

    missing = signed_in.get("/api/repository-browser", params={"path": str(root / "missing")})
    assert missing.status_code == 404


def test_browse_does_not_follow_a_symlink_outside_the_root(
    signed_in: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (root / "shortcut").symlink_to(secret, target_is_directory=True)
    signed_in.app.state.settings.repository_browser_roots = [root]

    listing = signed_in.get("/api/repository-browser", params={"path": str(root)})
    assert listing.json()["folders"] == []
    response = signed_in.get("/api/repository-browser", params={"path": str(root / "shortcut")})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "browser_path_outside_roots"
