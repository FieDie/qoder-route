"""Periodic model health probes.

Every `probe_interval_minutes` the router pings each Qoder model with a tiny
"Hello!" request and records TPS (tokens/sec) + alive/error status. Results are
kept in memory and served by /api/status/models. Probes do NOT touch account
stats (no mark_success/mark_failure) — they only measure model health.
"""
import asyncio
import logging
import asyncio
import time
from typing import Optional

from app.core.database import async_session
from app.services import direct_client, logbus, settings_service
from app.services.account_pool import pool
from app.services.qoder_client import QODER_MODEL_DISPLAY
from app.services.quota_service import looks_like_transient_stream_error, looks_like_model_queue

logger = logging.getLogger("qoderroute.probe")

PROBE_MESSAGE = "Hello!"

# level -> latest probe result
_results: dict[str, dict] = {}
_last_run: Optional[float] = None
_probing = False


# Generic Qoder tier names — the Status tab shows only the named models.
GENERIC_TIER_NAMES = {"Auto", "Ultimate", "Performance", "Efficient", "Lite", "Cantus"}


def _probe_models() -> list[tuple[str, str]]:
    """Named models only (Kimi-K3, Qwen3.8-Max, ...), deduped by level key."""
    seen: dict[str, str] = {}
    for display, level in QODER_MODEL_DISPLAY:
        if display in GENERIC_TIER_NAMES:
            continue
        if level not in seen:
            seen[level] = display
    return [(display, level) for level, display in seen.items()]


async def _probe_attempt(pat: str, display: str, level: str) -> dict:
    started = time.time()
    tokens = 0
    error: Optional[str] = None
    try:
        async for event in direct_client.run_infer(
            pat,
            level,
            [{"role": "user", "content": PROBE_MESSAGE}],
            max_tokens=32,
        ):
            if event["type"] == "done":
                u = event.get("usage") or {}
                # Use total_tokens instead of just completion_tokens for accurate TPS
                tokens = int(u.get("total_tokens") or u.get("completion_tokens") or 0)
            elif event["type"] == "error":
                error = event.get("message", "upstream error")
                # Queue error (10605) arrives as the FIRST event; the stream
                # then hangs until the connection drops (~67s). Stop reading
                # immediately so the queue error isn't overwritten by a
                # "stream interrupted" event from the connection drop.
                if looks_like_model_queue(error):
                    break
    except Exception as e:
        error = str(e)[:200]

    elapsed = max(time.time() - started, 0.001)
    tps = round(tokens / elapsed, 2) if tokens else 0.0

    # 10605: model is alive but parked in a server-side queue (isQueued).
    # Surface it explicitly so the Status tab can distinguish "broken" from
    # "temporarily queued".
    queued = error is not None and looks_like_model_queue(error)

    return {
        "model": level,
        "display": display,
        "alive": error is None,
        "is_queued": queued,
        "tps": tps,
        "tokens": tokens,
        "latency_ms": int(elapsed * 1000),
        "error": error,
        "at": time.time(),
    }


async def _probe_one(pat: str, display: str, level: str) -> dict:
    """Probe once; retry a single flaky connection drop before declaring dead."""
    result = await _probe_attempt(pat, display, level)
    if not result["alive"] and looks_like_transient_stream_error(result["error"] or ""):
        await asyncio.sleep(1)
        result = await _probe_attempt(pat, display, level)
    return result


async def probe_all() -> None:
    """Probe every model once. Safe to call from the background loop."""
    global _last_run, _probing
    if _probing:
        return
    _probing = True
    try:
        async with async_session() as db:
            account = await pool.get_next_account(db)
        if not account:
            logger.warning("Model probe skipped: no available accounts")
            for display, level in _probe_models():
                _results[level] = {
                    "model": level, "display": display, "alive": False,
                    "is_queued": False,
                    "tps": 0.0, "tokens": 0, "latency_ms": 0,
                    "error": "no available accounts", "at": time.time(),
                }
            _last_run = time.time()
            return

        for display, level in _probe_models():
            result = await _probe_one(account.pat_token, display, level)
            _results[level] = result
            logbus.push(
                "info" if result["alive"] else "warn", "probe",
                f"probe {display}: {'alive' if result['alive'] else 'error'} "
                f"{result['tps']} tps",
                model=level, tps=result["tps"], alive=result["alive"],
            )
        _last_run = time.time()
    finally:
        _probing = False


def snapshot() -> dict:
    return {
        "enabled": settings_service.get_probe_interval_minutes() > 0,
        "interval_minutes": settings_service.get_probe_interval_minutes(),
        "probing": _probing,
        "last_run": _last_run,
        "models": sorted(_results.values(), key=lambda m: m["display"]),
    }
