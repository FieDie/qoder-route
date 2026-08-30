import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.services import logbus, request_store

logger = logging.getLogger("qoderroute.api.logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])

STREAM_LIFETIME_SECONDS = 30.0
KEEPALIVE_SECONDS = 10.0


@router.get("")
async def get_logs(
    limit: int = Query(500, le=5000),
    after_seq: Optional[int] = None,
    account_id: Optional[int] = None,
    model: Optional[str] = None,
    outcome: Optional[str] = None,
):
    return {
        "logs": logbus.recent(limit=limit, after_seq=after_seq),
        "requests": logbus.requests(
            limit=200,
            account_id=account_id,
            model=model,
            outcome=outcome,
        ),
    }


@router.delete("")
async def clear_logs():
    """Wipe the live ring, request index, and persisted 24h summaries."""
    logbus.clear()
    cleared = await request_store.clear_all()
    return {"ok": True, "cleared_summaries": cleared}


@router.get("/requests")
async def get_request_summaries(
    limit: int = Query(200, le=2000),
    account_id: Optional[int] = None,
    model: Optional[str] = None,
    outcome: Optional[str] = None,
):
    return {
        "requests": logbus.requests(
            limit=limit,
            account_id=account_id,
            model=model,
            outcome=outcome,
        ),
    }


@router.get("/stream")
async def stream_logs():
    """SSE: replay the tail, then push every new event live."""
    async def gen():
        q = logbus.subscribe()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STREAM_LIFETIME_SECONDS
        try:
            # replay recent so the client isn't empty on connect
            for evt in logbus.recent(limit=200):
                yield f"data: {json.dumps(evt, default=str)}\n\n"
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    evt = await asyncio.wait_for(
                        q.get(),
                        timeout=min(KEEPALIVE_SECONDS, remaining),
                    )
                    yield f"data: {json.dumps(evt, default=str)}\n\n"
                except asyncio.TimeoutError:
                    if loop.time() < deadline:
                        yield ": keepalive\n\n"
        finally:
            logbus.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
