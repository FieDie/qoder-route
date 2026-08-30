import asyncio
import time
from collections import OrderedDict, deque
from typing import Optional

# Ring buffer of recent log events, plus a fan-out set of live SSE subscribers.
_buffer: deque[dict] = deque(maxlen=5000)
_subscribers: set[asyncio.Queue] = set()

# Latest snapshot per request_id (live + hydrated from SQLite).
_requests: OrderedDict[str, dict] = OrderedDict()
_REQUESTS_MAX = 2000

# Keep sequence numbers increasing across backend generations so EventSource
# clients can safely deduplicate after an automatic reconnect.
_seq = int(time.time() * 1_000_000)


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def _clean(extra: dict) -> dict:
    return {k: v for k, v in extra.items() if v is not None}


def _upsert_request(evt: dict) -> None:
    rid = evt.get("request_id")
    if not rid or not isinstance(rid, str):
        return
    prev = _requests.get(rid, {})
    terminal = evt.get("phase") in ("done", "error")
    row = {
        "request_id": rid,
        "ts": prev.get("ts") or evt["ts"],
        "last_ts": evt["ts"],
        "level": evt.get("level") or prev.get("level"),
        "source": evt.get("source") or prev.get("source"),
        "message": evt.get("message") or prev.get("message"),
        "dialect": evt.get("dialect") or prev.get("dialect"),
        "model": evt.get("model") or prev.get("model"),
        "account_id": (
            evt["account_id"] if evt.get("account_id") is not None
            else prev.get("account_id")
        ),
        "account_name": evt.get("account_name") or prev.get("account_name"),
        "phase": evt.get("phase") or prev.get("phase"),
        "outcome": evt.get("outcome") if evt.get("outcome") is not None else prev.get("outcome"),
        "prompt_tokens": evt.get("prompt_tokens", prev.get("prompt_tokens") or 0),
        "completion_tokens": evt.get("completion_tokens", prev.get("completion_tokens") or 0),
        "total_tokens": evt.get("total_tokens", prev.get("total_tokens") or 0),
        "credits": evt.get("credits", prev.get("credits") or 0),
        "latency_ms": evt.get("latency_ms") if evt.get("latency_ms") is not None else prev.get("latency_ms"),
        "first_token_ms": evt.get("first_token_ms") if evt.get("first_token_ms") is not None else prev.get("first_token_ms"),
        "thinking_chars": evt.get("thinking_chars", prev.get("thinking_chars")),
        "tool_calls": evt.get("tool_calls", prev.get("tool_calls")),
        "finish_reason": evt.get("finish_reason") or prev.get("finish_reason"),
        "live": not terminal,
    }
    if rid in _requests:
        del _requests[rid]
    _requests[rid] = row
    while len(_requests) > _REQUESTS_MAX:
        _requests.popitem(last=False)


def hydrate_request(row: dict) -> None:
    """Restore a persisted summary after restart (does not replay the event stream)."""
    rid = row.get("request_id")
    if not rid:
        return
    evt = {"ts": row.get("ts") or time.time(), **row, "phase": row.get("phase") or "done"}
    _upsert_request(evt)


def push(level: str, source: str, message: str, **extra):
    """Append a log event and broadcast to all live subscribers."""
    evt = {
        "seq": _next_seq(),
        "ts": time.time(),
        "level": level,
        "source": source,
        "message": message,
        **_clean(extra),
    }
    _buffer.append(evt)
    _upsert_request(evt)
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


def get_request(request_id: str) -> Optional[dict]:
    return _requests.get(request_id)


def requests(
    limit: int = 200,
    account_id: Optional[int] = None,
    model: Optional[str] = None,
    outcome: Optional[str] = None,
) -> list[dict]:
    items = list(_requests.values())
    if account_id is not None:
        items = [r for r in items if r.get("account_id") == account_id]
    if model:
        items = [r for r in items if r.get("model") == model]
    if outcome:
        items = [r for r in items if r.get("outcome") == outcome]
    return list(reversed(items[-limit:]))


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


def clear() -> None:
    """Drop the ring buffer and request index. Sequence numbers keep advancing."""
    _buffer.clear()
    _requests.clear()
