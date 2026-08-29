"""Resolve the Cosy/CLI version string from npm `@qoder-ai/qodercli`.

Hardcoding the version next to every upstream release is busywork.  We pull
the published latest on startup and refresh periodically; if npm is
unreachable the last good (or built-in fallback) value stays in use.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger("qoderroute.version")

NPM_LATEST_URL = "https://registry.npmjs.org/@qoder-ai/qodercli/latest"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
# Used only until the first successful npm fetch.
_FALLBACK_VERSION = "1.1.36"
_REFRESH_INTERVAL_SEC = 6 * 3600

_lock = asyncio.Lock()
_cached: str = _FALLBACK_VERSION
_fetched_at: float = 0.0
_source: str = "fallback"


def get() -> str:
    """Current Cosy/CLI version for User-Agent / Cosy-Version / business.version."""
    return _cached


def snapshot() -> dict:
    return {
        "version": _cached,
        "source": _source,
        "fetched_at": _fetched_at or None,
        "refresh_interval_sec": _REFRESH_INTERVAL_SEC,
    }


async def refresh(*, force: bool = False) -> str:
    """Fetch npm latest when stale (or always when ``force``)."""
    global _cached, _fetched_at, _source
    async with _lock:
        now = time.time()
        if (
            not force
            and _fetched_at
            and now - _fetched_at < _REFRESH_INTERVAL_SEC
        ):
            return _cached
        version = await _fetch_npm_version()
        if version:
            if version != _cached:
                logger.info("Qoder CLI version updated: %s → %s (npm)", _cached, version)
            else:
                logger.info("Qoder CLI version confirmed: %s (npm)", version)
            _cached = version
            _source = "npm"
            _fetched_at = now
        elif not _fetched_at:
            logger.warning(
                "Qoder CLI version fetch failed; using fallback %s",
                _cached,
            )
            _source = "fallback"
        return _cached


async def refresher_loop() -> None:
    while True:
        await asyncio.sleep(_REFRESH_INTERVAL_SEC)
        try:
            await refresh(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("version refresher error: %s", exc)


async def _fetch_npm_version() -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                NPM_LATEST_URL,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("npm latest HTTP %s", resp.status_code)
                return None
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("npm latest fetch failed: %s", exc)
        return None

    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str):
        logger.warning("npm latest missing version field")
        return None
    candidate = version.strip()
    if not _VERSION_RE.fullmatch(candidate):
        logger.warning("npm latest returned non-semver version: %r", candidate)
        return None
    return candidate
