"""`key -> value` lookups shared by the action, executor and confirmation registries."""


class UnknownKeyError(LookupError):
    pass


class Registry[T]:
    """A mapping populated by registration. A new variant is a new entry, never a branch."""

    def __init__(self, what: str) -> None:
        self._what = what
        self._entries: dict[str, T] = {}

    def register(self, key: str, value: T, *, replace: bool = False) -> None:
        # Silent replacement would let two modules fight over a key unnoticed.
        if key in self._entries and not replace:
            raise ValueError(f"{self._what} {key!r} is already registered")
        self._entries[key] = value

    def get(self, key: str) -> T:
        try:
            return self._entries[key]
        except KeyError:
            raise UnknownKeyError(f"no {self._what} registered as {key!r}") from None

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def keys(self) -> list[str]:
        return sorted(self._entries)

    def copy(self) -> "Registry[T]":
        clone = Registry[T](self._what)
        clone._entries = dict(self._entries)
        return clone
