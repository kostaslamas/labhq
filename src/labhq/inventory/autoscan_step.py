"""The program loop that runs the automatic scan: one registration, no logic of its own."""

from labhq.api.public_url import current_public_url
from labhq.cli.context import Context
from labhq.inventory.autoscan import run_autoscan
from labhq.inventory.settings import get_inventory_settings


async def autoscan_step(context: Context) -> int:
    """Returns how many new projects were announced (0 when nothing ran)."""
    async with context.sessions() as db:
        result = await run_autoscan(
            db, context.clock, get_inventory_settings(), public_url=current_public_url()
        )
        await db.commit()
        return result.announced
