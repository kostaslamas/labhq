"""The session inventory API: the folders the scan looks in, the sessions, and the actions."""

from fastapi import APIRouter

from labhq.api.inventory.routes import router as roots_router
from labhq.api.inventory.sessions import router as sessions_router

router = APIRouter()
router.include_router(roots_router)
router.include_router(sessions_router)

__all__ = ["router"]
