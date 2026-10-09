"""The cost of an analysis, estimated before it starts from sizes alone (no model call).

The inputs are the project's tracked code (bounded), its git history and diff (bounded) and
the tail of each transcript, so the size of each is known from file sizes and settings.
Amounts are integer micro-USD (ADR 0002).
"""

from dataclasses import dataclass
from pathlib import Path

from labhq.inventory.model import SavedEntry
from labhq.inventory.settings import InventorySettings

MILLION = 1_000_000


@dataclass(frozen=True)
class Estimate:
    kind: str
    account: str | None
    input_tokens: int
    output_tokens: int
    cost_micros: int
    transcripts: int

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def tracked_bytes(files: list[Path]) -> int:
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def estimate(
    *,
    kind: str,
    account: str | None,
    code_bytes: int,
    entries: list[SavedEntry],
    settings: InventorySettings,
) -> Estimate:
    per_token = settings.chars_per_token
    tail_chars = sum(
        min(_size(entry.location), settings.transcript_tail_chars) for entry in entries
    )
    chars = (
        min(code_bytes, settings.code_chars)
        + settings.diff_chars
        + settings.git_log_commits * 100
        + tail_chars
    )
    input_tokens = -(-chars // per_token)
    price = settings.price_per_million_tokens_micros.get(
        kind, settings.default_price_per_million_micros
    )
    tokens = input_tokens + settings.reply_tokens
    # Rounded up, so an estimate never understates.
    cost = -(-tokens * price // MILLION)
    return Estimate(kind, account, input_tokens, settings.reply_tokens, cost, len(entries))


def _size(path: Path | None) -> int:
    try:
        return path.stat().st_size if path is not None else 0
    except OSError:
        return 0
