"""The public address the running program serves, kept so other shells can find it.

`labhq serve` and onboarding learn the address; `labhq passkey enroll` runs in another
process and would otherwise print a link for `localhost`. A file in the data directory is
the one place both read, like the ntfy topic.
"""

from pathlib import Path

PUBLIC_URL_FILENAME = "public_url"


def load_public_url(data_dir: Path) -> str | None:
    try:
        text = (data_dir / PUBLIC_URL_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def store_public_url(data_dir: Path, url: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / PUBLIC_URL_FILENAME).write_text(url + "\n", encoding="utf-8")
