"""The approval notification links to the phone page, when a public URL is known."""

from collections.abc import Iterator

import pytest
from sqlalchemy import select

from labhq.api.public_url import announce_exposure
from labhq.db.models import Notification
from tests.approvals.conftest import World


@pytest.fixture(autouse=True)
def clean_urls(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("LABHQ_PUBLIC_URL", raising=False)
    announce_exposure(None)
    yield
    announce_exposure(None)


async def click_url(world: World) -> str | None:
    async with world.sessions() as db:
        return await db.scalar(select(Notification.click_url))


async def test_the_notification_links_to_the_approval_page(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.test")
    approval = await world.service.request("delete_branch", {"members": ["a"], "lead": "m"})
    assert await click_url(world) == f"https://labhq.example.test/approve/{approval.id}"


async def test_the_notification_has_no_link_without_a_public_url(world: World) -> None:
    await world.service.request("delete_branch", {"members": ["a"], "lead": "m"})
    assert await click_url(world) is None
