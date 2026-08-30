"""Persist terminal request summaries so Usage/Requests survive a restart."""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import delete, select

from app.core.database import async_session
from app.models.request_summary import RequestSummary
from app.services import logbus

logger = logging.getLogger("qoderroute.request_store")

RETENTION_SECONDS = 86400
_writes = 0


def _row_from_snapshot(snap: dict) -> dict:
    return {
        "request_id": str(snap["request_id"])[:32],
        "ts": float(snap.get("ts") or time.time()),
        "last_ts": float(snap.get("last_ts") or snap.get("ts") or time.time()),
        "dialect": snap.get("dialect"),
        "model": snap.get("model"),
        "account_id": snap.get("account_id"),
        "account_name": (str(snap["account_name"])[:128] if snap.get("account_name") else None),
        "phase": snap.get("phase"),
        "outcome": snap.get("outcome"),
        "completion_tokens": int(snap.get("completion_tokens") or 0),
        "credits": float(snap.get("credits") or 0.0),
        "latency_ms": snap.get("latency_ms"),
        "first_token_ms": snap.get("first_token_ms"),
        "message": (snap.get("message") or "")[:256],
        "level": snap.get("level"),
    }


async def persist_snapshot(snap: dict) -> None:
    global _writes
    row = _row_from_snapshot(snap)
    try:
        async with async_session() as session:
            existing = await session.get(RequestSummary, row["request_id"])
            if existing is None:
                session.add(RequestSummary(**row))
            else:
                for key, value in row.items():
                    if key != "request_id":
                        setattr(existing, key, value)
            _writes += 1
            if _writes % 25 == 0:
                cutoff = time.time() - RETENTION_SECONDS
                await session.execute(
                    delete(RequestSummary).where(RequestSummary.ts < cutoff)
                )
            await session.commit()
    except Exception as e:
        logger.warning("request summary persist failed: %s", e)


def schedule(evt: dict) -> None:
    """Fire-and-forget persist of the current in-memory snapshot for this request."""
    rid = evt.get("request_id")
    if not rid:
        return
    snap = logbus.get_request(rid) or {
        "request_id": rid,
        "ts": evt.get("ts"),
        "last_ts": evt.get("ts"),
        **evt,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(persist_snapshot(snap), name="request-summary-persist")


async def load_recent() -> int:
    """Hydrate the in-memory request index from the last 24h of SQLite rows."""
    cutoff = time.time() - RETENTION_SECONDS
    async with async_session() as session:
        result = await session.execute(
            select(RequestSummary)
            .where(RequestSummary.ts >= cutoff)
            .order_by(RequestSummary.ts.asc())
        )
        rows = result.scalars().all()
    for row in rows:
        logbus.hydrate_request({
            "request_id": row.request_id,
            "ts": row.ts,
            "last_ts": row.last_ts,
            "dialect": row.dialect,
            "model": row.model,
            "account_id": row.account_id,
            "account_name": row.account_name,
            "phase": row.phase,
            "outcome": row.outcome,
            "completion_tokens": row.completion_tokens,
            "credits": row.credits,
            "latency_ms": row.latency_ms,
            "first_token_ms": row.first_token_ms,
            "message": row.message,
            "level": row.level,
            "live": False,
        })
    logger.info("Hydrated %d request summaries", len(rows))
    return len(rows)


async def clear_all() -> int:
    """Wipe persisted request summaries (used by DELETE /api/logs)."""
    async with async_session() as session:
        result = await session.execute(delete(RequestSummary))
        await session.commit()
        count = result.rowcount or 0
    logger.info("Cleared %d request summaries", count)
    return count
