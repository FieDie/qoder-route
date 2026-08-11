import asyncio
import time
from collections import deque
from typing import Optional

# Ring buffer of recent log events, plus a fan-out set of live SSE subscribers.
_buffer: deque[dict] = deque(maxlen=2000)
_subscribers: set[asyncio.Queue] = set()

# Keep sequence numbers increasing across backend generations so EventSource
# clients can safely deduplicate after an automatic reconnect.
_seq = int(time.time() * 1_000_000)


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def push(level: str, source: str, message: str, **extra):
    """Append a log event and broadcast to all live subscribers."""
    evt = {
        "seq": _next_seq(),
        "ts": time.time(),
        "level": level,
        "source": source,
        "message": message,
        **extra,
    }
    _buffer.append(evt)
    for q in list(_subscribers):
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            pass
    return evt


def recent(limit: int = 200, after_seq: Optional[int] = None) -> list[dict]:
    items = list(_buffer)
    if after_seq is not None:
        items = [e for e in items if e["seq"] > after_seq]
    return items[-limit:]


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)
