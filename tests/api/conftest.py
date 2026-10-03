from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import Request

from labhq.api.deps import Owner, ResolverRegistry
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.settings import Settings

OWNER_HEADER = "X-Test-Owner"


async def header_resolver(request: Request) -> Owner | None:
    """A stand-in for Passkeys: whoever sends the test header is the owner."""
    subject = request.headers.get(OWNER_HEADER)
    return Owner(subject) if subject else None


@pytest.fixture
def resolvers() -> ResolverRegistry:
    registry = ResolverRegistry()
    registry.register("test-header", header_resolver)
    return registry


@pytest.fixture
def api_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(ui_dir=tmp_path / "no-ui", default_page_size=2, max_page_size=3)


@pytest.fixture
async def context(database_url: str, tmp_path: Path, clock: FakeClock) -> AsyncIterator[Context]:
    engine = create_engine(database_url)
    settings = Settings(data_dir=tmp_path / "data", database_url=database_url)
    try:
        yield Context(settings, session_factory(engine), clock)
    finally:
        await engine.dispose()
