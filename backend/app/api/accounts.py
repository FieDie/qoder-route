import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.schemas import (
    AccountCreate, AccountOut, AccountPoolStatus, DashboardStats
)
from app.models.account import Account
from app.services.account_pool import pool
from app.services.qoder_client import validate_pat, QODER_MODEL_DISPLAY
from app.services import logbus
from app.services import quota_service

logger = logging.getLogger("qoderroute.api.accounts")
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# ── Static routes FIRST (before /{account_id} shadow-catches them) ──

# Legacy fallback: completions used to be identified only by message text.
# New events carry phase=done + outcome=ok. Keep the spellings so a buffer
# still holding pre-schema lines counts, and so a new dialect cannot silently
# vanish from Usage if someone forgets the structured fields.
_COMPLETION_MESSAGES = frozenset({
    "stream done",              # OpenAI streaming
    "completion ok",            # OpenAI non-streaming
    "anthropic stream done",    # Anthropic streaming
    "anthropic completion ok",  # Anthropic non-streaming
})


def _is_completion(e: dict) -> bool:
    if e.get("source") != "chat":
        return False
    if e.get("phase") == "done" and e.get("outcome") == "ok":
        return True
    return e.get("message") in _COMPLETION_MESSAGES


@router.get("/stats/activity")
async def dashboard_activity():
    """Recent chat traffic aggregated from the in-memory log bus.

    Covers the last 60 minutes (or since server start, whichever is shorter):
    per-minute request/token series plus per-model usage totals. Tokens are
    completion tokens, matching the lifetime counters on accounts.
    """
    now = time.time()
    window_sec = 3600
    bucket_sec = 60
    n_buckets = window_sec // bucket_sec
    # Align buckets to whole wall-clock minutes. A floating `now`-anchored
    # window makes bucket edges drift on every poll — the chart morphs even
    # with zero new traffic.
    end = int(now // bucket_sec) * bucket_sec
    start = end - window_sec

    series = [
        {"t": start + i * bucket_sec, "requests": 0, "tokens": 0}
        for i in range(n_buckets + 1)
    ]
    by_model: dict[str, dict] = {}
    totals = {"requests": 0, "tokens": 0, "credits": 0.0}

    seen: set[str] = set()

    def _count(e: dict, ts: float) -> None:
        nonlocal totals
        tokens = int(e.get("completion_tokens") or 0)
        credits = float(e.get("credits") or 0.0)
        idx = min(int((ts - start) // bucket_sec), n_buckets)
        series[idx]["requests"] += 1
        series[idx]["tokens"] += tokens
        totals["requests"] += 1
        totals["tokens"] += tokens
        totals["credits"] += credits

        key = str(e.get("model") or "unknown")
        slot = by_model.setdefault(key, {"model": key, "requests": 0, "tokens": 0, "credits": 0.0})
        slot["requests"] += 1
        slot["tokens"] += tokens
        slot["credits"] += credits

    for e in logbus.recent(limit=5000):
        if not _is_completion(e):
            continue
        ts = float(e.get("ts") or 0)
        if ts < start:
            continue
        rid = str(e.get("request_id") or f"seq:{e.get('seq')}")
        if rid in seen:
            continue
        seen.add(rid)
        _count(e, ts)

    # Hydrated SQLite summaries after a restart — the ring buffer is empty
    # but these rows still feed the Usage charts.
    for r in logbus.requests(limit=2000):
        if r.get("outcome") != "ok":
            continue
        ts = float(r.get("last_ts") or r.get("ts") or 0)
        if ts < start:
            continue
        rid = str(r.get("request_id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        _count(r, ts)

    display = {key: name for name, key in QODER_MODEL_DISPLAY}
    models = sorted(by_model.values(), key=lambda m: m["requests"], reverse=True)
    for m in models:
        m["display"] = display.get(m["model"], m["model"])
        m["credits"] = round(m["credits"], 2)

    return {
        "bucket_sec": bucket_sec,
        "series": series,
        "by_model": models,
        "window": {
            "requests": totals["requests"],
            "tokens": totals["tokens"],
            "credits": round(totals["credits"], 2),
        },
    }


@router.get("/stats/dashboard", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    stats = await pool.get_stats(db)
    accounts = await pool.list_accounts(db)
    exhausted = sum(1 for a in accounts if a.is_quota_exceeded)

    return DashboardStats(
        total_accounts=stats["total_accounts"],
        active_accounts=stats["active_accounts"],
        available_now=stats["available_now"],
        accounts_in_cooldown=stats["accounts_in_cooldown"],
        accounts_exhausted=exhausted,
        total_requests=stats["total_requests"],
        total_tokens=stats["total_tokens"],
        credits_spent=stats["credits_spent"],
        recent_errors=[
            {
                "account_id": a.id,
                "account_name": a.name,
                "message": a.last_error_message,
                "at": a.last_error_at.isoformat() if a.last_error_at else None,
            }
            for a in accounts
            if a.last_error_message
        ][:20],
    )


# ── Collection routes ──

@router.get("", response_model=AccountPoolStatus)
async def list_accounts(db: AsyncSession = Depends(get_db)):
    accounts = await pool.list_accounts(db)
    stats = await pool.get_stats(db)
    return AccountPoolStatus(
        total_accounts=stats["total_accounts"],
        active_accounts=stats["active_accounts"],
        available_accounts=stats["available_now"],
        accounts_in_cooldown=stats["accounts_in_cooldown"],
        total_requests=stats["total_requests"],
        accounts=[AccountOut.model_validate(a) for a in accounts],
    )


# ── Filtered account views ──

@router.get("/available")
async def list_available_accounts(db: AsyncSession = Depends(get_db)):
    """Only available accounts — mirrors the routing filters in get_next_account."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    stmt = select(Account).where(
        and_(
            Account.is_active == True,
            Account.is_available == True,
            Account.is_quota_exceeded == False,
            (Account.quota_remaining.is_(None)) | (Account.quota_remaining > 0),
            (Account.cooldown_until.is_(None)) | (Account.cooldown_until < now),
            Account.consecutive_failures < settings.max_consecutive_failures,
        )
    )
    result = await db.execute(stmt)
    accounts = result.scalars().all()

    return {
        "filter": "available",
        "count": len(accounts),
        "accounts": [AccountOut.model_validate(a) for a in accounts],
    }


@router.get("/exhausted")
async def list_exhausted_accounts(db: AsyncSession = Depends(get_db)):
    """Only exhausted accounts (is_quota_exceeded == True)."""
    from sqlalchemy import and_
    
    stmt = select(Account).where(
        and_(
            Account.is_active == True,
            Account.is_quota_exceeded == True,
        )
    )
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    
    return {
        "filter": "exhausted",
        "count": len(accounts),
        "accounts": [AccountOut.model_validate(a) for a in accounts],
    }


@router.post("", response_model=AccountOut)
async def create_account(body: AccountCreate, db: AsyncSession = Depends(get_db)):
    valid, msg = await validate_pat(body.pat_token)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Token validation failed: {msg}")

    # Reject plan-less (free tier) accounts up front. An account WITH a plan
    # but no quota is still added — the quota refresh parks it as exhausted.
    # Credits on Qoder are one-shot, so a failed plan fetch must not skip
    # this check and let a free PAT into the pool.
    pq = await quota_service.fetch_plan_quota(body.pat_token)
    # fetch_plan_quota returns a partial dict when only userinfo/quota answered;
    # without the plan payload the tier is unknown and the free-tier check below
    # would silently pass.
    if pq is None or not pq.get("plan_fetched", True):
        raise HTTPException(
            status_code=400,
            detail="Could not fetch plan/quota from Qoder — not added. Retry when the API is reachable.",
        )
    tier = str(pq.get("plan_tier") or "").strip().lower()
    if tier == "personal_standard":
        raise HTTPException(
            status_code=400,
            detail="Free plan (personal_standard) — this account has no plan. Not added.",
        )

    try:
        account = await pool.add_account(
            db,
            name=quota_service.resolve_account_name(body.name, pq),
            pat_token=body.pat_token,
            priority=body.priority,
            model_level=body.model_level,
            default_model=body.default_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await pool.refresh_quota(account.id)
    # refresh_quota wrote through its own session; ``db`` still holds the
    # pre-quota row in its identity map, so re-read it before responding.
    try:
        await db.refresh(account)
    except Exception:  # noqa: BLE001 — auto-delete may have removed it already
        pass
    return AccountOut.model_validate(account)


# ── Item routes LAST ──

@router.delete("/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    success = await pool.remove_account(db, account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}


@router.post("/{account_id}/quota/refresh")
async def refresh_account_quota(account_id: int):
    data = await pool.refresh_quota(account_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Account not found or quota fetch failed")
    return {"ok": True, "quota": data}


@router.get("/{account_id}/pat")
async def reveal_account_pat(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the full PAT for clipboard copy. Localhost panel — no redaction."""
    acc = await pool.get_account_by_id(db, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"pat": acc.pat_token}
