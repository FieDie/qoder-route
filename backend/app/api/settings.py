import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import settings_service
from app.services import api_key_service
from app.services import model_catalog
from app.services.settings_service import PROBE_INTERVALS

logger = logging.getLogger("qoderroute.api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    worker_logs_enabled: Optional[bool] = None
    worker_retry_allow: Optional[bool] = None
    worker_proxy_use: Optional[bool] = None
    accounts_show_email: Optional[bool] = None
    accounts_show_tokens: Optional[bool] = None
    accounts_show_requests: Optional[bool] = None
    accounts_auto_delete_exhausted: Optional[bool] = None
    auth_enabled: Optional[bool] = None
    qoder_infer_base: Optional[Literal["api1", "api2", "api3"]] = None
    probe_interval_minutes: Optional[int] = None
    probe_model_keys: Optional[list[str]] = None


@router.get("")
async def get_settings():
    return settings_service.snapshot()


@router.put("")
async def update_settings(body: SettingsUpdate):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if values.get("auth_enabled") is True:
        if await api_key_service.count() == 0:
            raise HTTPException(
                status_code=400,
                detail="Create an API key before enabling authentication",
            )
    if "probe_interval_minutes" in values and values["probe_interval_minutes"] not in PROBE_INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"probe_interval_minutes must be one of {list(PROBE_INTERVALS)}",
        )
    if "probe_model_keys" in values:
        unknown = sorted(set(values["probe_model_keys"]) - model_catalog.model_keys())
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model key(s): {', '.join(unknown)}",
            )
    updated = await settings_service.update(values)

    # Flipping auto-delete on sweeps the pool right away — every currently
    # exhausted account is removed in one go.
    if values.get("accounts_auto_delete_exhausted"):
        from app.services.account_pool import pool
        removed = await pool.delete_exhausted_accounts()
        if removed:
            logger.info(f"Auto-delete sweep removed {removed} exhausted account(s)")

    return updated
