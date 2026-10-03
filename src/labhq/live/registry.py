"""Topics as registrations: a name and the one-row query that yields its watermark.

A watermark is a handful of aggregates (highest id, row count, latest instants) chosen so
that any insert, delete or state change a page cares about moves at least one of them. It
is cheap on the indexed tables and sees writes from every process, because it reads SQLite.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, case, func, select
from sqlalchemy.orm import InstrumentedAttribute

type WatermarkQuery = Callable[[], Select[Any]]


@dataclass(frozen=True)
class Topic:
    name: str
    query: WatermarkQuery


class TopicRegistry:
    def __init__(self) -> None:
        self._topics: dict[str, Topic] = {}

    def register(self, name: str, query: WatermarkQuery) -> None:
        if name in self._topics:
            raise ValueError(f"Live topic {name!r} is already registered.")
        self._topics[name] = Topic(name, query)

    def names(self) -> list[str]:
        return list(self._topics)

    def __iter__(self) -> Iterator[Topic]:
        # A copy: a topic registered while a pass runs is picked up on the next one.
        return iter(list(self._topics.values()))

    def __len__(self) -> int:
        return len(self._topics)


def aggregates(*columns: ColumnElement[Any]) -> WatermarkQuery:
    """The watermark query for one table: `select(*columns)`, a single row."""

    def query() -> Select[Any]:
        return select(*columns)

    return query


def status_counts(
    column: InstrumentedAttribute[Any], values: Iterable[Any]
) -> list[ColumnElement[Any]]:
    """Rows per status: any transition moves two counts, even one that sets no timestamp."""
    return [func.sum(case((column == value, 1), else_=0)) for value in values]


default_topics = TopicRegistry()
