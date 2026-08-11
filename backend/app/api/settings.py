import logging
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import settings_service

logger = logging.getLogger("qoderroute.api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    worker_logs_enabled: Optional[bool] = None
    worker_retry_allow: Optional[bool] = None
    accounts_show_email: Optional[bool] = None
    accounts_show_tokens: Optional[bool] = None
    accounts_show_requests: Optional[bool] = None
    account_activity_checks_enabled: Optional[bool] = None
    qoder_infer_base: Optional[Literal["api1", "api2", "api3"]] = None
    probe_interval_minutes: Optional[int] = None


@router.get("")
async def get_settings():
    return settings_service.snapshot()


@router.put("")
async def update_settings(body: SettingsUpdate):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    return await settings_service.update(values)
