import asyncio
import json
import uuid
import time
from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.services.account_pool import pool
from app.services import direct_client, logbus
from app.services.qoder_client import resolve_model_level
from app.services.quota_service import (
    looks_like_quota_error,
    looks_like_model_queue,
    looks_like_rate_limit,
    looks_like_transient_stream_error,
    parse_model_queue,
)

router = APIRouter(tags=["chat"])

MAX_SWAP_ATTEMPTS = 3
MODEL_QUEUE_RETRY_DELAY = 3.0


def classify_chat_error(message: str, error_scope: str | None = None) -> str:
    """Classify an error by the component whose health it represents."""
    normalized = (message or "").strip().casefold()
    normalized_scope = (error_scope or "").strip().casefold()
    if normalized_scope == "infrastructure" or normalized.startswith("signer unavailable") or normalized.startswith("signer unavailable:"):
        return "infrastructure"
    if looks_like_model_queue(message):
        return "model_queue"
    # Probe-generated queue error from /direct_client: "model queued (10605)"
    if "model queued" in normalized and "10605" in normalized:
        return "model_queue"
    if normalized_scope == "quota" or looks_like_quota_error(message):
        return "quota"
    # Session blocked (416) is a transient server-side throttle, not an
    # account failure — don't penalize the account with mark_failure.
    if "416" in normalized and "session blocked" in normalized:
        return "infrastructure"
    if looks_like_rate_limit(message):
        return "infrastructure"
    return "account"


def _client_session_id(headers: Mapping[str, str]) -> str | None:
    """Read the stable conversation id emitted by OpenCode.

    OpenCode supplies both headers.  Prefer the explicit session header and
    validate it before allowing it into the signed Qoder request.
    """
    for header_name in ("x-session-id", "x-session-affinity"):
        session_id = direct_client.normalize_session_id(headers.get(header_name))
        if session_id:
            return session_id
    return None


def _openai_chunk(chunk_id: str, model: str, created: int, delta: dict, finish_reason: str | None = None, usage: dict | None = None) -> str:
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage:
        payload["usage"] = usage
    return f"data: {json.dumps(payload)}\n\n"


def _resolve_level(requested: str) -> str:
    """Model comes from the request, not the account. Every account can serve
    every model in the Qoder pool."""
    if requested and requested.lower() != "auto":
        resolved = resolve_model_level(requested)
        if resolved != "auto":
            return resolved
    return "auto"


def _merge_tool_call_fragments(
    accumulator: dict[int, dict],
    fragments: list[dict],
) -> None:
    """Assemble OpenAI streaming tool-call deltas for a JSON response."""
    for position, fragment in enumerate(fragments):
        index = fragment.get("index", position)
        if not isinstance(index, int):
            index = position
        current = accumulator.setdefault(
            index,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        fragment_id = fragment.get("id")
        if isinstance(fragment_id, str) and fragment_id:
            if not current["id"]:
                current["id"] = fragment_id
            elif fragment_id != current["id"]:
                current["id"] += fragment_id
        if fragment.get("type"):
            current["type"] = fragment["type"]
        function = fragment.get("function") or {}
        name = function.get("name")
        if isinstance(name, str) and name:
            if not current["function"]["name"]:
                current["function"]["name"] = name
            elif name != current["function"]["name"]:
                current["function"]["name"] += name
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            current["function"]["arguments"] += arguments


def _finalize_tool_calls(accumulator: dict[int, dict]) -> list[dict]:
    calls: list[dict] = []
    for index in sorted(accumulator):
        call = accumulator[index]
        if not call["id"]:
            call["id"] = f"call_{uuid.uuid4().hex[:20]}"
        calls.append(call)
    return calls


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    messages_dicts = [m.model_dump() for m in body.messages]
    session_id = _client_session_id(request.headers)
    tried_ids: set[int] = set()
    model_level = _resolve_level(body.model)

    for _ in range(MAX_SWAP_ATTEMPTS):
        account = await pool.get_next_account(
            db,
            exclude_ids=tried_ids,
            model_level=model_level,
        )
        if not account:
            break

        tried_ids.add(account.id)
        account_id = account.id
        pat_token = account.pat_token
        def start_gen():
            return direct_client.run_infer(
                pat_token,
                model_level,
                messages_dicts,
                body.tools,
                body.reasoning_effort,
                body.fast,
                body.context_window,
                body.max_tokens,
                session_id,
            )

        if body.stream:
            gen = start_gen()
            # Probe the first event before committing the SSE stream so an
            # upstream error (403, etc.) surfaces with its real status instead
            # of a 200 OK with [error] text buried in the body.
            try:
                first = await gen.__anext__()
            except StopAsyncIteration:
                first = {"type": "error", "message": "empty upstream response"}

            # Flaky connection drop on the very first event — retry once.
            if first.get("type") == "error" and looks_like_transient_stream_error(first.get("message", "")):
                logbus.push("info", "chat", f"transient stream drop — retrying in 1s: {first.get('message', '')[:120]}", account_id=account_id, model=model_level)
                await asyncio.sleep(1)
                gen = start_gen()
                try:
                    first = await gen.__anext__()
                except StopAsyncIteration:
                    first = {"type": "error", "message": "empty upstream response"}

            # 10605 with an empty queue (isQueued=false): the model may clear
            # in a moment — wait 3s and retry once before surfacing the error.
            if first.get("type") == "error" and classify_chat_error(first.get("message", ""), first.get("error_scope")) == "model_queue":
                queue = parse_model_queue(first.get("message", ""))
                if queue is not None and queue.get("isQueued") is False:
                    logbus.push("info", "chat", "model queue empty (10605, isQueued=false) — retrying in 3s", account_id=account_id, model=model_level)
                    await asyncio.sleep(MODEL_QUEUE_RETRY_DELAY)
                    gen = start_gen()
                    try:
                        first = await gen.__anext__()
                    except StopAsyncIteration:
                        first = {"type": "error", "message": "empty upstream response"}

            if first.get("type") == "error":
                msg = first.get("message", "upstream error")
                error_kind = classify_chat_error(msg, first.get("error_scope"))
                if error_kind == "infrastructure":
                    logbus.push("error", "chat", f"local infrastructure error: {msg[:200]}", account_id=account_id, model=model_level)
                    raise HTTPException(status_code=first.get("status") or 503, detail=msg)
                if error_kind == "model_queue":
                    # 10605: model queued upstream — don't fail the account.
                    logbus.push("warn", "chat", f"model queued: {msg[:200]}", account_id=account_id, model=model_level)
                    raise HTTPException(status_code=first.get("status") or 503, detail=msg)
                if error_kind == "quota":
                    logbus.push("warn", "chat", "quota exceeded, swapping account", account_id=account_id, model=model_level)
                    await pool.mark_quota_exceeded(account_id)
                    continue  # auto-swap to the next account
                logbus.push("error", "chat", f"upstream error: {msg[:200]}", account_id=account_id, model=model_level)
                await pool.mark_failure(account_id, msg)
                raise HTTPException(status_code=first.get("status") or 502, detail=msg)

            return _sse_response(
                account_id,
                model_level,
                body.model or model_level,
                gen,
                first,
            )

        queue_retried = False
        transient_retried = False
        while True:
            final_text = ""
            final_thinking = ""
            final_reasoning_signature = ""
            final_reasoning_item: dict | None = None
            final_tool_call_fragments: dict[int, dict] = {}
            final_function_call: dict = {}
            tool_call_chunks = 0
            tool_call_entries = 0
            final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            final_diagnostics: dict = {}
            final_finish_reason: str | None = None
            error_msg = None
            error_status = None
            error_scope = None

            async for event in start_gen():
                if event["type"] == "text":
                    final_text += event["text"]
                elif event["type"] == "thinking":
                    final_thinking += event["thinking"]
                elif event["type"] == "reasoning_signature":
                    final_reasoning_signature += event["signature"]
                elif event["type"] == "reasoning_item":
                    final_reasoning_item = event["reasoning_item"]
                elif event["type"] == "tool_calls":
                    tool_call_chunks += 1
                    tool_call_entries += len(event["tool_calls"])
                    _merge_tool_call_fragments(
                        final_tool_call_fragments,
                        event["tool_calls"],
                    )
                elif event["type"] == "function_call":
                    fragment = event["function_call"]
                    if fragment.get("name"):
                        final_function_call["name"] = (
                            final_function_call.get("name", "") + fragment["name"]
                        )
                    if fragment.get("arguments"):
                        final_function_call["arguments"] = (
                            final_function_call.get("arguments", "")
                            + fragment["arguments"]
                        )
                elif event["type"] == "done":
                    u = event.get("usage") or {}
                    final_diagnostics = event.get("diagnostics") or {}
                    final_finish_reason = event.get("finish_reason")
                    final_usage = {
                        "prompt_tokens": u.get("prompt_tokens", 0),
                        "completion_tokens": u.get("completion_tokens", 0),
                        "total_tokens": u.get("total_tokens", 0),
                        "credits": u.get("credits") or u.get("total_credits") or 0.0,
                    }
                elif event["type"] == "error":
                    error_msg = event["message"]
                    error_status = event.get("status")
                    error_scope = event.get("error_scope")

            # Flaky mid-stream connection drop — retry once before failing.
            if error_msg is not None and looks_like_transient_stream_error(error_msg) and not transient_retried:
                transient_retried = True
                logbus.push("info", "chat", f"transient stream drop — retrying in 1s: {error_msg[:120]}", account_id=account_id, model=model_level)
                await asyncio.sleep(1)
                continue

            # 10605 with an empty queue (isQueued=false): the model may clear
            # in a moment — wait 3s and retry once before surfacing the error.
            if error_msg is not None and classify_chat_error(error_msg, error_scope) == "model_queue":
                queue = parse_model_queue(error_msg)
                if queue is not None and queue.get("isQueued") is False and not queue_retried:
                    queue_retried = True
                    logbus.push("info", "chat", "model queue empty (10605, isQueued=false) — retrying in 3s", account_id=account_id, model=model_level)
                    await asyncio.sleep(MODEL_QUEUE_RETRY_DELAY)
                    continue
                logbus.push("warn", "chat", f"model queued: {error_msg[:200]}", account_id=account_id, model=model_level)
                raise HTTPException(status_code=error_status or 503, detail=error_msg)
            break

        if error_msg is not None:
            error_kind = classify_chat_error(error_msg, error_scope)
            if error_kind == "infrastructure":
                logbus.push("error", "chat", f"local infrastructure error: {error_msg[:200]}", account_id=account_id, model=model_level)
                raise HTTPException(status_code=error_status or 503, detail=error_msg)
            if error_kind == "quota":
                logbus.push("warn", "chat", f"quota exceeded, swapping account", account_id=account_id, model=model_level)
                await pool.mark_quota_exceeded(account_id)
                continue  # auto-swap to the next account
            logbus.push("error", "chat", f"upstream error: {error_msg[:200]}", account_id=account_id, model=model_level)
            await pool.mark_failure(account_id, error_msg)
            raise HTTPException(status_code=error_status or 502, detail=error_msg)

        upstream_credits = final_usage.get("credits") or 0.0
        activity_consumed = await pool.mark_success(
            account_id,
            final_usage.get("completion_tokens", 0),
            upstream_credits,
            model_level,
        )
        if activity_consumed is True:
            final_usage["credits"] = 0.0
        final_tool_calls = _finalize_tool_calls(final_tool_call_fragments)
        logbus.push(
            "info", "chat", f"completion ok",
            account_id=account_id, model=model_level,
            prompt_tokens=final_usage.get("prompt_tokens", 0),
            completion_tokens=final_usage.get("completion_tokens", 0),
            total_tokens=final_usage.get("total_tokens", 0),
            thinking_chars=len(final_thinking),
            reasoning_item=final_reasoning_item is not None,
            reasoning_signature_chars=len(final_reasoning_signature),
            tool_call_chunks=tool_call_chunks,
            tool_call_fragments=tool_call_entries,
            tool_calls=len(final_tool_calls),
            function_call=bool(final_function_call),
            finish_reason=final_finish_reason,
            credits=final_usage.get("credits", 0),
            activity_free_call=activity_consumed is True,
            upstream_reported_credits=(
                upstream_credits if activity_consumed is True else 0.0
            ),
            **final_diagnostics,
        )

        message: dict = {"role": "assistant", "content": final_text}
        if final_thinking:
            message["reasoning_content"] = final_thinking
        if final_reasoning_signature:
            # Keep both spellings: Qoder streams `signature`, while its native
            # history representation calls the same value this longer name.
            message["signature"] = final_reasoning_signature
            message["reasoning_content_signature"] = final_reasoning_signature
        if final_reasoning_item is not None:
            message["reasoning_item"] = final_reasoning_item
        if final_tool_calls:
            message["tool_calls"] = final_tool_calls
        if final_function_call:
            message["function_call"] = final_function_call

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=body.model or model_level,
            choices=[{
                "index": 0,
                "message": message,
                "finish_reason": final_finish_reason
                or ("tool_calls" if final_tool_calls else "function_call" if final_function_call else "stop"),
            }],
            usage={
                "prompt_tokens": final_usage.get("prompt_tokens", 0),
                "completion_tokens": final_usage.get("completion_tokens", 0),
                "total_tokens": final_usage.get("total_tokens", 0),
            },
        )

    raise HTTPException(
        status_code=503,
        detail="No available accounts. All accounts are exhausted, in cooldown, or inactive.",
    )


def _sse_response(
    account_id: int,
    model_level: str,
    model: str,
    gen,
    first_event: dict,
) -> StreamingResponse:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    async def _chain():
        """Yield the pre-pulled first event, then the rest of the generator."""
        yield first_event
        async for e in gen:
            yield e

    async def event_stream():
        yield _openai_chunk(chunk_id, model, created, {"role": "assistant", "content": ""})

        errored = False
        saw_done = False
        saw_tool_calls = False
        tool_call_chunks = 0
        tool_call_entries = 0
        function_call_chunks = 0
        thinking_chars = 0
        reasoning_item_count = 0
        reasoning_signature_chars = 0
        text_chars = 0
        try:
            async for event in _chain():
                if event["type"] == "text":
                    text_chars += len(event["text"])
                    yield _openai_chunk(chunk_id, model, created, {"content": event["text"]})
                elif event["type"] == "thinking":
                    thinking_chars += len(event["thinking"])
                    yield _openai_chunk(chunk_id, model, created, {"reasoning_content": event["thinking"]})
                elif event["type"] == "reasoning_item":
                    reasoning_item_count += 1
                    yield _openai_chunk(
                        chunk_id,
                        model,
                        created,
                        {"reasoning_item": event["reasoning_item"]},
                    )
                elif event["type"] == "reasoning_signature":
                    signature = event["signature"]
                    reasoning_signature_chars += len(signature)
                    yield _openai_chunk(
                        chunk_id,
                        model,
                        created,
                        {
                            "signature": signature,
                            "reasoning_content_signature": signature,
                        },
                    )
                elif event["type"] == "tool_calls":
                    saw_tool_calls = True
                    tool_call_chunks += 1
                    tool_call_entries += len(event["tool_calls"])
                    yield _openai_chunk(chunk_id, model, created, {"tool_calls": event["tool_calls"]})
                elif event["type"] == "function_call":
                    saw_tool_calls = True
                    function_call_chunks += 1
                    yield _openai_chunk(
                        chunk_id,
                        model,
                        created,
                        {"function_call": event["function_call"]},
                    )
                elif event["type"] == "done":
                    saw_done = True
                    usage = event.get("usage") or {}
                    diagnostics = event.get("diagnostics") or {}
                    upstream_credits = usage.get("credits") or usage.get("total_credits") or 0.0
                    activity_consumed = await pool.mark_success(
                        account_id,
                        usage.get("completion_tokens", 0),
                        upstream_credits,
                        model_level,
                    )
                    if activity_consumed is True:
                        usage = dict(usage)
                        usage["credits"] = 0.0
                        if "total_credits" in usage:
                            usage["total_credits"] = 0.0
                    logbus.push(
                        "info", "chat", f"stream done",
                        account_id=account_id, model=model_level,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        thinking_chars=thinking_chars,
                        reasoning_items=reasoning_item_count,
                        reasoning_signature_chars=reasoning_signature_chars,
                        text_chars=text_chars,
                        tool_call_chunks=tool_call_chunks,
                        tool_call_entries=tool_call_entries,
                        function_call_chunks=function_call_chunks,
                        finish_reason=event.get("finish_reason"),
                        credits=usage.get("credits", 0),
                        activity_free_call=activity_consumed is True,
                        upstream_reported_credits=(
                            upstream_credits if activity_consumed is True else 0.0
                        ),
                        **diagnostics,
                    )
                    yield _openai_chunk(
                        chunk_id,
                        model,
                        created,
                        {},
                        event.get("finish_reason")
                        or ("tool_calls" if saw_tool_calls else "stop"),
                        usage=usage,
                    )
                elif event["type"] == "error":
                    errored = True
                    error_kind = classify_chat_error(
                        event["message"],
                        event.get("error_scope"),
                    )
                    if error_kind == "quota":
                        logbus.push("warn", "chat", f"quota exceeded (stream)", account_id=account_id, model=model_level)
                        await pool.mark_quota_exceeded(account_id)
                    elif error_kind == "model_queue":
                        logbus.push("warn", "chat", f"model queued (stream): {event['message'][:200]}", account_id=account_id, model=model_level)
                    elif error_kind == "infrastructure":
                        logbus.push("error", "chat", f"local infrastructure error (stream): {event['message'][:200]}", account_id=account_id, model=model_level)
                    else:
                        msg = event["message"]
                        if looks_like_transient_stream_error(msg) or looks_like_rate_limit(msg):
                            # flaky network / upstream backpressure — not the
                            # account's fault, don't burn its failure budget
                            logbus.push("warn", "chat", f"transient stream error (no account penalty): {msg[:200]}", account_id=account_id, model=model_level)
                        else:
                            logbus.push("error", "chat", f"stream error: {msg[:200]}", account_id=account_id, model=model_level)
                            await pool.mark_failure(account_id, msg)
                    yield _openai_chunk(chunk_id, model, created, {"content": f"[error] {event['message']}"}, "stop")
        except Exception as e:
            errored = True
            logbus.push("error", "chat", f"stream exception: {str(e)[:200]}", account_id=account_id, model=model_level)
            # Exceptions in router/SSE processing are local infrastructure
            # failures. Explicit upstream account errors arrive as events.
            yield _openai_chunk(chunk_id, model, created, {"content": f"[error] {e}"}, "stop")

        if not errored and not saw_done:
            yield _openai_chunk(chunk_id, model, created, {}, "stop")

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
