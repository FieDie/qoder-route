"""Sync the runtime model catalog from Qoder's signed model-list endpoint.

The upstream catalog is dynamic — price factors follow promotions and new
models appear without a client release.  This service fetches the live list
through the signer's /sign_get (WASM `qodercontext_prepareRequest`), merges
it over the static baseline in model_catalog.py, and persists the snapshot
to data/model_catalog_sync.json so it survives container restarts.
"""
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models.account import Account
from app.services import logbus, model_catalog, quota_service, settings_service, signer_service

logger = logging.getLogger("qoderroute.model_sync")

SYNC_INTERVAL_SECONDS = 6 * 3600
_STORE_FILENAME = "model_catalog_sync.json"

_TIER_KEYS = frozenset({"auto", "ultimate", "performance", "efficient", "lite"})


def _store_path() -> Path:
    return Path(settings.data_dir) / _STORE_FILENAME


def _convert_entry(m: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map an upstream model-list row onto the local catalog row shape."""
    key = str(m.get("key") or "").strip()
    if not key or m.get("enable") is False:
        return None
    thinking_config = m.get("thinking_config") or {}
    enabled = thinking_config.get("enabled") or {}
    efforts_map = enabled.get("efforts") or {}
    efforts = list(efforts_map.keys())
    default_effort = next(
        (k for k, v in efforts_map.items() if isinstance(v, dict) and v.get("is_default")),
        None,
    )
    windows = m.get("available_context_windows")
    if not windows:
        cfg = m.get("context_config") or {}
        windows = sorted(
            int(v["token_count"])
            for v in cfg.values()
            if isinstance(v, dict) and isinstance(v.get("token_count"), (int, float))
        )
    try:
        factor = float(m.get("price_factor"))
    except (TypeError, ValueError):
        factor = 0.0
    try:
        max_input = int(m.get("max_input_tokens") or 180_000)
    except (TypeError, ValueError):
        max_input = 180_000
    return {
        "key": key,
        "name": str(m.get("display_name") or key),
        "credit_factor": factor,
        "is_reasoning": bool(m.get("is_reasoning")),
        "is_vision": bool(m.get("is_vl")),
        "max_input_tokens": max_input,
        "context_windows": [int(w) for w in windows or []],
        "probe_default": False,
        "kind": "tier" if key in _TIER_KEYS else "model",
        "thinking_enabled": bool(enabled) or "enabled" in thinking_config,
        "thinking_efforts": efforts,
        "default_thinking_effort": default_effort,
    }


def _merge_with_baseline(converted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upstream rows win for shared keys; baseline-only keys are preserved."""
    upstream_by_key = {e["key"]: e for e in converted}
    merged: list[dict[str, Any]] = []
    for base in model_catalog.MODEL_CATALOG:
        row = dict(base)
        up = upstream_by_key.get(str(base["key"]))
        if up is not None:
            row.update({k: v for k, v in up.items() if k != "probe_default"})
            row["probe_default"] = base["probe_default"]
        merged.append(row)
    baseline_keys = {str(e["key"]) for e in model_catalog.MODEL_CATALOG}
    for up in converted:
        if up["key"] not in baseline_keys:
            merged.append(up)
    return merged


def load_synced() -> int:
    """Restore a persisted snapshot into memory. Returns the entry count."""
    path = _store_path()
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("models") or []
        if entries:
            model_catalog.apply_dynamic_catalog(entries)
        return len(entries)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not restore synced model catalog: %s", exc)
        return 0


def _persist(entries: list[dict[str, Any]], synced_at: float) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"synced_at": synced_at, "models": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def sync_status() -> dict[str, Any]:
    """Last sync snapshot info for the panel (never raises)."""
    count = len(model_catalog.effective_catalog())
    path = _store_path()
    if not path.exists():
        return {"ok": True, "synced_at": None, "model_count": count}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "synced_at": payload.get("synced_at"),
            "model_count": len(payload.get("models") or []),
        }
    except (OSError, ValueError):
        return {"ok": True, "synced_at": None, "model_count": count}


async def sync_model_catalog() -> dict[str, Any]:
    """Fetch the live catalog, merge it over the baseline and activate it."""
    async with async_session() as session:
        acct = (
            await session.execute(
                select(Account).where(Account.is_active == True).limit(1)  # noqa: E712
            )
        ).scalars().first()
    if acct is None:
        return {"ok": False, "error": "No active account to authenticate the sync"}

    pat = acct.pat_token
    jt = await quota_service.get_job_token(pat)
    if not jt:
        return {"ok": False, "error": "Job token exchange failed"}
    uid = await quota_service.get_uid(pat) or ""
    host = f"https://{settings_service.get('qoder_infer_base')}.qoder.sh"

    async with httpx.AsyncClient(timeout=25) as client:
        signed = await signer_service.post_to_signer(
            "/sign_get",
            json={
                "jt": jt,
                "uid": uid,
                "machine_id": acct.machine_id,
                "base_url": host,
                "url_path": "/api/v2/model/list?Encode=1",
            },
            client=client,
        )
        payload = signed.json()
        request_url = payload.get("url")
        if not request_url:
            return {"ok": False, "error": "Signer did not return a signed URL"}
        gr = await client.get(
            request_url,
            headers={**quota_service._base_headers(), **(payload.get("headers") or {})},
        )
    if gr.status_code != 200:
        return {"ok": False, "error": f"Upstream HTTP {gr.status_code}"}
    try:
        rows = gr.json().get("chat") or []
    except ValueError:
        return {"ok": False, "error": "Upstream returned a non-JSON payload"}

    converted = [e for e in (_convert_entry(m) for m in rows) if e]
    if not converted:
        return {"ok": False, "error": "Upstream returned an empty model list"}

    before_keys = model_catalog.model_keys()
    merged = _merge_with_baseline(converted)
    model_catalog.apply_dynamic_catalog(merged)
    synced_at = time.time()
    _persist(merged, synced_at)

    added = len({e["key"] for e in merged} - before_keys)
    logbus.push("info", "routing", f"Model catalog synced: {len(merged)} models (+{added} new)")
    return {
        "ok": True,
        "synced_at": synced_at,
        "model_count": len(merged),
        "added": added,
        "updated": len(merged) - added,
    }


async def sync_loop() -> None:
    """Periodic background sync; failures simply wait for the next cycle."""
    while True:
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
        try:
            await sync_model_catalog()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Model catalog sync failed", exc_info=True)
