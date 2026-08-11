import logging

from fastapi import APIRouter

from app.services import model_probe

logger = logging.getLogger("qoderroute.api.status")
router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("/models")
async def model_status():
    return model_probe.snapshot()
