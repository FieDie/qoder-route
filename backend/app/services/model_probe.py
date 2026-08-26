"""Periodic model health probes.

Every `probe_interval_minutes` the router pings each Qoder model with a tiny
"Hello!" request and records TPS (tokens/sec) + alive/error status. Results are
kept in memory and served by /api/status/models. Successful probes call
mark_success so one-shot credits drain the same local quota as live traffic,
and they reuse the account's machine_id so Qoder does not see a second device.
"""
import asyncio
import logging
import time
from typing import Optional

from app.core.database import async_session
from app.services import direct_client, logbus, settings_service
from app.services.account_pool import pool
from app.services.model_catalog import MODEL_CATALOG
from app.services.quota_service import (
    looks_like_transient_stream_error,
    looks_like_model_queue,
    looks_like_quota_error,
)

logger = logging.getLogger("qoderroute.probe")

PROBE_MESSAGE = "Hello!"

# level -> latest probe result
_results: dict[str, dict] = {}
_last_run: Optional[float] = None
_probing = False


def _probe_models() -> list[tuple[str, str]]:
    """Models selected in Settings, in stable catalog order."""
    selected = set(settings_service.get_probe_model_keys())
    return [
        (str(entry["name"]), str(entry["key"]))
        for entry in MODEL_CATALOG
        if entry["key"] in selected
    ]


async def _probe_attempt(
    pat: str,
    display: str,
    level: str,
    machine_id: Optional[str] = None,
) -> dict:
    started = time.time()
    tokens = 0
    completion_tokens = 0
    credits = 0.0
    error: Optional[str] = None
    try:
        async for event in direct_client.run_infer(
            pat,
            level,
            [{"role": "user", "content": PROBE_MESSAGE}],
            max_tokens=32,
            machine_id=machine_id,
        ):
            if event["type"] == "done":
                u = event.get("usage") or {}
                # Use total_tokens instead of just completion_tokens for accurate TPS
                tokens = int(u.get("total_tokens") or u.get("completion_tokens") or 0)
                completion_tokens = int(u.get("completion_tokens") or 0)
                credits = float(u.get("credits") or u.get("total_credits") or 0.0)
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
        "completion_tokens": completion_tokens,
        "credits": credits,
        "latency_ms": int(elapsed * 1000),
        "error": error,
        "at": time.time(),
    }


async def _probe_one(
    pat: str,
    display: str,
    level: str,
    machine_id: Optional[str] = None,
) -> dict:
    """Probe once; retry a single flaky connection drop before declaring dead."""
    result = await _probe_attempt(pat, display, level, machine_id=machine_id)
    if not result["alive"] and looks_like_transient_stream_error(result["error"] or ""):
        await asyncio.sleep(1)
        result = await _probe_attempt(pat, display, level, machine_id=machine_id)
    return result


async def probe_all() -> None:
    """Probe every model once. Safe to call from the background loop."""
    global _last_run, _probing
    if _probing:
        return
    _probing = True
    try:
        probe_models = _probe_models()
        if not probe_models:
            _last_run = time.time()
            return
        async with async_session() as db:
            account = await pool.get_next_account(db)
            account_id = account.id if account else None
            pat = account.pat_token if account else None
            machine_id = getattr(account, "machine_id", None) if account else None
        if not account or account_id is None or not pat:
            logger.warning("Model probe skipped: no available accounts")
            for display, level in probe_models:
                _results[level] = {
                    "model": level, "display": display, "alive": False,
                    "is_queued": False,
                    "tps": 0.0, "tokens": 0, "latency_ms": 0,
                    "error": "no available accounts", "at": time.time(),
                }
            _last_run = time.time()
            return

        for display, level in probe_models:
            result = await _probe_one(pat, display, level, machine_id=machine_id)
            _results[level] = result
            if result["alive"]:
                await pool.mark_success(
                    account_id,
                    int(result.get("completion_tokens") or 0),
                    float(result.get("credits") or 0.0),
                )
            elif looks_like_quota_error(result.get("error") or ""):
                await pool.mark_quota_exceeded(account_id)
                logbus.push(
                    "warn", "probe",
                    f"probe {display}: quota exceeded, parking account",
                    model=level, account_id=account_id,
                )
                break
            logbus.push(
                "info" if result["alive"] else "warn", "probe",
                f"probe {display}: {'alive' if result['alive'] else 'error'} "
                f"{result['tps']} tps",
                model=level, tps=result["tps"], alive=result["alive"],
                credits=result.get("credits") or 0.0,
            )
        _last_run = time.time()
    finally:
        _probing = False


def snapshot() -> dict:
    selected = set(settings_service.get_probe_model_keys())
    return {
        "enabled": settings_service.get_probe_interval_minutes() > 0,
        "interval_minutes": settings_service.get_probe_interval_minutes(),
        "probing": _probing,
        "last_run": _last_run,
        "models": sorted(
            (result for key, result in _results.items() if key in selected),
            key=lambda m: m["display"],
        ),
    }
