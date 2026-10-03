"""Shared sentence helpers: every answer is built from short, plain sentences."""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta

from labhq.clock import Clock
from labhq.speech import say_ago

TITLE_WORDS = 8
FREE_TEXT_WORDS = 20
LISTED = 3

# Characters that trip `speakable` (tables, JSON, headings, code) and carry nothing aloud.
_UNSPEAKABLE = re.compile(r"[|{}\[\]`#_]")


def clean(text: str, max_words: int = TITLE_WORDS) -> str:
    """Flatten user-written text into one speakable run of at most `max_words` words."""
    words = _UNSPEAKABLE.sub(" ", text).split()
    spoken = " ".join(words[:max_words])
    return f"{spoken} and so on" if len(words) > max_words else spoken


def name_list(items: Sequence[str], total: int | None = None) -> str:
    """Say up to `LISTED` items, then how many more there are."""
    shown = list(items[:LISTED])
    extra = (total if total is not None else len(items)) - len(shown)
    if extra > 0:
        shown.append(f"{extra} more")
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def since_phrase(since: datetime | None, clock: Clock) -> str:
    if since is None:
        return "today"
    delta = max(clock.now() - since, timedelta(0))
    return f"since {say_ago(delta)}"
