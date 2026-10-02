"""`adapter_key -> factory`. A new adapter is a new registration, never a dispatcher edit."""

from collections.abc import Callable

from labhq.adapters.base import Adapter

AdapterFactory = Callable[[], Adapter]


class UnknownAdapterError(LookupError):
    pass


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, key: str, factory: AdapterFactory, *, replace: bool = False) -> None:
        # Silent replacement would let two modules fight over a key unnoticed.
        if key in self._factories and not replace:
            raise ValueError(f"adapter {key!r} is already registered")
        self._factories[key] = factory

    def create(self, key: str) -> Adapter:
        try:
            factory = self._factories[key]
        except KeyError:
            raise UnknownAdapterError(f"no adapter registered as {key!r}") from None
        return factory()

    def adapter_keys(self) -> list[str]:
        return sorted(self._factories)

    def copy(self) -> "AdapterRegistry":
        clone = AdapterRegistry()
        clone._factories = dict(self._factories)
        return clone
