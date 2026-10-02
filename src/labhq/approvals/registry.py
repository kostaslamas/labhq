"""A named-entry registry, shared by action types, executors and confirmation kinds."""

from collections.abc import Iterator


class UnknownEntryError(LookupError):
    pass


class Registry[V]:
    """`key -> value`. A new variant is a new registration, never a dispatcher edit."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._entries: dict[str, V] = {}

    def register(self, key: str, value: V, *, replace: bool = False) -> None:
        # Silent replacement would let two modules fight over a key unnoticed.
        if key in self._entries and not replace:
            raise ValueError(f"{self.kind} {key!r} is already registered")
        self._entries[key] = value

    def get(self, key: str) -> V:
        try:
            return self._entries[key]
        except KeyError:
            raise UnknownEntryError(f"no {self.kind} registered as {key!r}") from None

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._entries))

    def copy(self) -> "Registry[V]":
        clone = Registry[V](self.kind)
        clone._entries = dict(self._entries)
        return clone
