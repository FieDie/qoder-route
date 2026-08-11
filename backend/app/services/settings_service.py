"""DB-backed runtime settings with an in-memory cache.

Reads are synchronous dict lookups, so hot paths (e.g. the worker log
reader checking a flag per line) never touch the database.
"""
import logging
from typing import Optional

from sqlalchemy import select

from app.core.database import async_session
from app.models.app_setting import AppSetting

logger = logging.getLogger("qoderroute.settings")

SettingValue = bool | str | int

_QODER_INFER_BASES = frozenset({"api1", "api2", "api3"})
PROBE_INTERVALS = (0, 5, 10, 15, 20, 25, 30, 60)  # minutes; 0 disables probing

_DEFAULTS: dict[str, SettingValue] = {
    "worker_logs_enabled": True,
    "worker_retry_allow": False,
    "accounts_show_email": True,
    "accounts_show_tokens": True,
    "accounts_show_requests": True,
    "accounts_auto_delete_exhausted": False,
    "accounts_auto_delete_keep_activity": True,
    "account_activity_checks_enabled": True,
    "qoder_infer_base": "api3",
    "probe_interval_minutes": 15,
}

_cache: dict[str, SettingValue] = dict(_DEFAULTS)


def _normalize_value(key: str, value: object) -> Optional[SettingValue]:
    """Validate a setting supplied by the API or read from storage."""
    default = _DEFAULTS.get(key)
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if value == "true":
            return True
        if value == "false":
            return False
        return None
    if key == "qoder_infer_base" and isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in _QODER_INFER_BASES:
            return candidate
    if key == "probe_interval_minutes":
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return None
        return minutes if minutes in PROBE_INTERVALS else None
    return None


def _serialize_value(value: SettingValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def load() -> None:
    """Pull persisted values into the cache. Called once at startup."""
    async with async_session() as session:
        rows = (await session.execute(select(AppSetting))).scalars().all()
    loaded = dict(_DEFAULTS)
    for row in rows:
        normalized = _normalize_value(row.key, row.value)
        if normalized is not None:
            loaded[row.key] = normalized
    _cache.clear()
    _cache.update(loaded)
    logger.info(f"Settings loaded: {_cache}")


def get(key: str) -> SettingValue:
    return _cache.get(key, _DEFAULTS.get(key, False))


def get_probe_interval_minutes() -> int:
    value = _cache.get("probe_interval_minutes", _DEFAULTS["probe_interval_minutes"])
    normalized = _normalize_value("probe_interval_minutes", value)
    return int(normalized if normalized is not None else _DEFAULTS["probe_interval_minutes"])


def get_qoder_infer_base() -> str:
    value = _cache.get("qoder_infer_base", _DEFAULTS["qoder_infer_base"])
    normalized = _normalize_value("qoder_infer_base", value)
    return str(normalized or _DEFAULTS["qoder_infer_base"])


def snapshot() -> dict[str, SettingValue]:
    return {key: _cache.get(key, default) for key, default in _DEFAULTS.items()}


async def update(values: dict[str, SettingValue]) -> dict[str, SettingValue]:
    """Persist known keys and refresh the cache. Unknown keys are ignored."""
    normalized_values: dict[str, SettingValue] = {}
    for key, value in values.items():
        normalized = _normalize_value(key, value)
        if normalized is not None:
            normalized_values[key] = normalized

    async with async_session() as session:
        for key, value in normalized_values.items():
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=_serialize_value(value)))
            else:
                row.value = _serialize_value(value)
        await session.commit()
    _cache.update(normalized_values)
    return snapshot()
