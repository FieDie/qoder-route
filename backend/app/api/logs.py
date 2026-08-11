import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.services import logbus

logger = logging.getLogger("qoderroute.api.logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])

STREAM_LIFETIME_SECONDS = 30.0
KEEPALIVE_SECONDS = 10.0


@router.get("")
async def get_logs(limit: int = Query(200, le=2000), after_seq: Optional[int] = None):
    return {"logs": logbus.recent(limit=limit, after_seq=after_seq)}


@router.get("/stream")
async def stream_logs():
    """SSE: replay the tail, then push every new event live."""
    async def gen():
        q = logbus.subscribe()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STREAM_LIFETIME_SECONDS
        try:
            # replay recent so the client isn't empty on connect
            for evt in logbus.recent(limit=100):
                yield f"data: {json.dumps(evt)}\n\n"
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    evt = await asyncio.wait_for(
                        q.get(),
                        timeout=min(KEEPALIVE_SECONDS, remaining),
                    )
                    yield f"data: {json.dumps(evt)}\n\n"
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
