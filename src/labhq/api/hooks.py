"""Lifespan hooks as registrations: a later issue attaches state without editing `app.py`.

A hook is an async context manager factory taking the app: code before its `yield` runs at
startup, code after it at shutdown. Hooks start in registration order and stop in reverse.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

LifespanHook = Callable[[FastAPI], AbstractAsyncContextManager[None]]


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, LifespanHook] = {}

    def register(self, name: str, hook: LifespanHook) -> None:
        if name in self._hooks:
            raise ValueError(f"Lifespan hook {name!r} is already registered.")
        self._hooks[name] = hook

    def __iter__(self) -> Iterator[LifespanHook]:
        return iter(self._hooks.values())

    def __len__(self) -> int:
        return len(self._hooks)


def lifespan_of(
    hooks: list[LifespanHook],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for hook in hooks:
                await stack.enter_async_context(hook(app))
            yield

    return lifespan


default_hooks = HookRegistry()
