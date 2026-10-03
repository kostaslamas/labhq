"""The exposure contract: something that makes a local port reachable from outside."""

from typing import Protocol


class ExposureError(RuntimeError):
    """Exposure could not be set up; the message tells the operator what to do."""


class Exposure(Protocol):
    """A running exposure. Closing it must be safe to repeat."""

    @property
    def url(self) -> str:
        """The public base URL, without a path and without a trailing slash."""
        ...

    def close(self) -> None: ...


class ExposureAdapter(Protocol):
    def open(self, port: int) -> Exposure:
        """Start exposing `127.0.0.1:<port>`; raises `ExposureError` on failure."""
        ...
