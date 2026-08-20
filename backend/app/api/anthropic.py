"""Anthropic-compatible /v1/messages endpoint.

Translates the Anthropic Messages API — request format, SSE streaming events,
error bodies — onto the internal Qoder pipeline so clients like Claude Code or
any anthropic-sdk-based tool can talk to the router natively.

Differences handled here:
  - `system` is a top-level param, not a message
  - content is block-based (text / thinking / tool_use / tool_result / image)
  - tools use `input_schema` instead of OpenAI's `parameters`
  - streaming uses named SSE events (message_start, content_block_delta, ...)
  - usage is input_tokens/output_tokens, stop_reason is end_turn/tool_use/...
"""
import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.account_pool import pool
from app.services import direct_client, logbus
from app.services.qoder_client import resolve_model_level
from app.services.quota_service import (
    looks_like_transient_stream_error,
    parse_model_queue,
)
from app.api.chat import (
    classify_chat_error,
    _client_session_id,
    _merge_tool_call_fragments,
    _finalize_tool_calls,
    MAX_SWAP_ATTEMPTS,
    MODEL_QUEUE_RETRY_DELAY,
)

router = APIRouter(tags=["anthropic"])

# Claude model-name hints → internal levels. Anything else (including the
# router's own keys like `gmodel`) goes through resolve_model_level first.
_CLAUDE_ALIAS_HINTS = (
    ("opus", "ultimate"),
    ("sonnet", "performance"),
    ("haiku", "efficient"),
)


class AnthropicMessage(BaseModel):
    role: str
    content: Optional[object] = None


class AnthropicRequest(BaseModel):
    model: str = "auto"
    messages: list[AnthropicMessage]
    max_tokens: int = 4096
    system: Optional[object] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    tools: Optional[list[dict]] = None
    tool_choice: Optional[dict] = None
    thinking: Optional[dict] = None
    metadata: Optional[dict] = None


def _anthropic_error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": error_type, "message": message}},
    )


import re


def _resolve_level(requested: str) -> str:
    # Claude Code appends context-window suffixes like "[1m]" or "[200k]"
    # to model names; strip them so "glm-5.3[1m]" resolves like "glm-5.3".
    requested = re.sub(r"\[\d+[km]\]$", "", requested.strip())
    if requested and requested.lower() != "auto":
        resolved = resolve_model_level(requested)
        if resolved != "auto":
            return resolved
        low = requested.lower()
        for hint, level in _CLAUDE_ALIAS_HINTS:
            if hint in low:
                return level
    return "auto"


def _system_text(system: object) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p)
    return ""


def _tool_result_content(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for sub in content:
            if isinstance(sub, dict):
                if sub.get("type") == "text":
                    parts.append(sub.get("text", ""))
                elif sub.get("type") == "image":
                    parts.append("[image omitted]")
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def _image_block_to_openai(block: dict) -> Optional[dict]:
    source = block.get("source") or {}
    if source.get("type") == "base64":
        url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
        return {"type": "image_url", "image_url": {"url": url}}
    if source.get("type") == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url", "")}}
    return None


def _convert_messages(body: AnthropicRequest) -> list[dict]:
    """Anthropic messages → OpenAI-style message dicts for run_infer."""
    out: list[dict] = []
    system = _system_text(body.system)
    if system:
        out.append({"role": "system", "content": system})

    # Map tool_use id → tool name so tool_result messages can carry the
    # function name (OpenCode/OpenAI clients include it; Qoder's history
    # format expects it for continuity in tool loops).
    tool_name_by_id: dict[str, str] = {}

    for msg in body.messages:
        role = msg.role if msg.role in ("user", "assistant") else "user"
        content = msg.content

        if isinstance(content, str) or content is None:
            out.append({"role": role, "content": content or ""})
            continue

        if not isinstance(content, list):
            out.append({"role": role, "content": json.dumps(content, ensure_ascii=False)})
            continue

        texts: list[str] = []
        thinking_text = ""
        thinking_signature = ""
        tool_calls: list[dict] = []
        tool_messages: list[dict] = []
        image_parts: list[dict] = []
        passthrough_blocks: list[dict] = []

        for block in content:
            if not isinstance(block, dict):
                texts.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                texts.append(block.get("text", ""))
            elif btype == "thinking":
                thinking_text += block.get("thinking", "")
                if block.get("signature"):
                    thinking_signature += block["signature"]
            elif btype == "redacted_thinking":
                # opaque encrypted reasoning state — pass through for
                # _normalize_message to restore as reasoning_item
                passthrough_blocks.append(block)
            elif btype == "tool_use" and role == "assistant":
                call_id = block.get("id") or f"call_{uuid.uuid4().hex[:20]}"
                tool_name_by_id[call_id] = block.get("name", "")
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                })
            elif btype == "tool_result":
                tool_message = {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": _tool_result_content(block),
                }
                # attach the function name from the originating tool_use
                name = tool_name_by_id.get(block.get("tool_use_id", ""))
                if name:
                    tool_message["name"] = name
                tool_messages.append(tool_message)
            elif btype == "image":
                converted = _image_block_to_openai(block)
                if converted:
                    image_parts.append(converted)

        # tool_result blocks answer the previous assistant tool_use turn —
        # they must precede any new user text in OpenAI history order.
        out.extend(tool_messages)

        if role == "assistant":
            message: dict = {"role": "assistant", "content": "\n".join(t for t in texts if t)}
            if thinking_text:
                message["reasoning_content"] = thinking_text
            # Preserve the signature so Qoder's reasoning state survives
            # multi-turn tool loops (dropping it breaks agentic continuity).
            if thinking_signature:
                message["reasoning_content_signature"] = thinking_signature
                message["signature"] = thinking_signature
            if passthrough_blocks:
                message["content"] = (
                    [{"type": "text", "text": "\n".join(t for t in texts if t)}]
                    if any(t for t in texts) else []
                ) + passthrough_blocks
            if tool_calls:
                message["tool_calls"] = tool_calls
            out.append(message)
        else:
            text = "\n".join(t for t in texts if t)
            if image_parts:
                parts: list[dict] = []
                if text:
                    parts.append({"type": "text", "text": text})
                parts.extend(image_parts)
                out.append({"role": "user", "content": parts})
            elif text:
                out.append({"role": "user", "content": text})

    return out


def _convert_tools(tools: Optional[list[dict]]) -> Optional[list[dict]]:
    if not tools:
        return None
    converted = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "custom" and tool.get("input_schema") is not None:
            # Anthropic server-tool style custom tool
            converted.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object"},
                },
            })
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema")
                or tool.get("function", {}).get("parameters")
                or {"type": "object"},
            },
        })
    return converted or None


def _convert_tool_choice(tool_choice: Optional[dict]) -> Optional[object]:
    if not isinstance(tool_choice, dict):
        return None
    choice_type = tool_choice.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "tool":
        return {
            "type": "function",
            "function": {"name": tool_choice.get("name", "")},
        }
    return None


def _reasoning_effort_from_thinking(thinking: Optional[dict]) -> Optional[str]:
    if not isinstance(thinking, dict):
        return None
    if thinking.get("type") != "enabled":
        return None
    budget = thinking.get("budget_tokens")
    if isinstance(budget, (int, float)):
        if budget >= 10_000:
            return "high"
        if budget >= 4_000:
            return "medium"
        return "low"
    return "high"


def _stop_reason_openai_to_anthropic(finish_reason: Optional[str], has_tools: bool) -> str:
    if has_tools:
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    if finish_reason and finish_reason.startswith("stop_sequence"):
        return "stop_sequence"
    return "end_turn"


def _sse_event(event_name: str, data: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/v1/messages")
async def create_message(
    body: AnthropicRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    messages_dicts = _convert_messages(body)
    tools = _convert_tools(body.tools)
    tool_choice = _convert_tool_choice(body.tool_choice)
    reasoning_effort = _reasoning_effort_from_thinking(body.thinking)
    session_id = _client_session_id(request.headers)
    tried_ids: set[int] = set()
    model_level = _resolve_level(body.model)

    for _ in range(MAX_SWAP_ATTEMPTS):
        account = await pool.get_next_account(db, exclude_ids=tried_ids)
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
                tools,
                reasoning_effort,
                None,
                None,
                body.max_tokens,
                session_id,
                machine_id=getattr(account, "machine_id", None),
            )

        if body.stream:
            gen = start_gen()
            try:
                first = await gen.__anext__()
            except StopAsyncIteration:
                first = {"type": "error", "message": "empty upstream response"}

            if first.get("type") == "error" and looks_like_transient_stream_error(first.get("message", "")):
                logbus.push("info", "chat", f"anthropic: transient stream drop — retrying in 1s: {first.get('message', '')[:120]}", account_id=account_id, model=model_level)
                await asyncio.sleep(1)
                gen = start_gen()
                try:
                    first = await gen.__anext__()
                except StopAsyncIteration:
                    first = {"type": "error", "message": "empty upstream response"}

            if first.get("type") == "error" and classify_chat_error(first.get("message", ""), first.get("error_scope")) == "model_queue":
                queue = parse_model_queue(first.get("message", ""))
                if queue is not None and queue.get("isQueued") is False:
                    logbus.push("info", "chat", "anthropic: model queue empty (10605) — retrying in 3s", account_id=account_id, model=model_level)
                    await asyncio.sleep(MODEL_QUEUE_RETRY_DELAY)
                    gen = start_gen()
                    try:
                        first = await gen.__anext__()
                    except StopAsyncIteration:
                        first = {"type": "error", "message": "empty upstream response"}

            if first.get("type") == "error":
                return await _handle_first_error(first, account_id, model_level)

            return _anthropic_sse_response(
                account_id,
                model_level,
                body.model or model_level,
                gen,
                first,
            )

        # --- non-streaming -------------------------------------------------
        queue_retried = False
        transient_retried = False
        while True:
            final_text = ""
            final_thinking = ""
            final_reasoning_signature = ""
            final_tool_call_fragments: dict[int, dict] = {}
            final_function_call: dict = {}
            final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
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
                elif event["type"] == "tool_calls":
                    _merge_tool_call_fragments(final_tool_call_fragments, event["tool_calls"])
                elif event["type"] == "function_call":
                    fragment = event["function_call"]
                    if fragment.get("name"):
                        final_function_call["name"] = final_function_call.get("name", "") + fragment["name"]
                    if fragment.get("arguments"):
                        final_function_call["arguments"] = final_function_call.get("arguments", "") + fragment["arguments"]
                elif event["type"] == "done":
                    u = event.get("usage") or {}
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

            if error_msg is not None and looks_like_transient_stream_error(error_msg) and not transient_retried:
                transient_retried = True
                logbus.push("info", "chat", f"anthropic: transient drop — retrying in 1s: {error_msg[:120]}", account_id=account_id, model=model_level)
                await asyncio.sleep(1)
                continue

            if error_msg is not None and classify_chat_error(error_msg, error_scope) == "model_queue":
                queue = parse_model_queue(error_msg)
                if queue is not None and queue.get("isQueued") is False and not queue_retried:
                    queue_retried = True
                    logbus.push("info", "chat", "anthropic: model queue empty (10605) — retrying in 3s", account_id=account_id, model=model_level)
                    await asyncio.sleep(MODEL_QUEUE_RETRY_DELAY)
                    continue
                logbus.push("warn", "chat", f"anthropic: model queued: {error_msg[:200]}", account_id=account_id, model=model_level)
                return _anthropic_error(error_status or 503, "api_error", error_msg)
            break

        if error_msg is not None:
            error_kind = classify_chat_error(error_msg, error_scope)
            if error_kind == "quota":
                logbus.push("warn", "chat", "anthropic: quota exceeded, swapping account", account_id=account_id, model=model_level)
                await pool.mark_quota_exceeded(account_id)
                continue
            if error_kind == "infrastructure":
                logbus.push("error", "chat", f"anthropic: infrastructure error: {error_msg[:200]}", account_id=account_id, model=model_level)
                return _anthropic_error(error_status or 503, "api_error", error_msg)
            logbus.push("error", "chat", f"anthropic: upstream error: {error_msg[:200]}", account_id=account_id, model=model_level)
            await pool.mark_failure(account_id, error_msg)
            return _anthropic_error(error_status or 502, "api_error", error_msg)

        await pool.mark_success(
            account_id,
            final_usage.get("completion_tokens", 0),
            final_usage.get("credits") or 0.0,
        )
        final_tool_calls = _finalize_tool_calls(final_tool_call_fragments)

        content_blocks: list[dict] = []
        if final_thinking:
            thinking_block = {"type": "thinking", "thinking": final_thinking}
            if final_reasoning_signature:
                thinking_block["signature"] = final_reasoning_signature
            content_blocks.append(thinking_block)
        content_blocks.append({"type": "text", "text": final_text})
        for call in final_tool_calls:
            try:
                tool_input = json.loads(call["function"]["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                tool_input = {"_raw": call["function"]["arguments"]}
            content_blocks.append({
                "type": "tool_use",
                "id": call["id"],
                "name": call["function"]["name"],
                "input": tool_input,
            })
        if final_function_call:
            try:
                tool_input = json.loads(final_function_call.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                tool_input = {"_raw": final_function_call.get("arguments")}
            content_blocks.append({
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": final_function_call.get("name", ""),
                "input": tool_input,
            })

        has_tools = bool(final_tool_calls or final_function_call)
        logbus.push(
            "info", "chat", "anthropic completion ok",
            account_id=account_id, model=model_level,
            prompt_tokens=final_usage.get("prompt_tokens", 0),
            completion_tokens=final_usage.get("completion_tokens", 0),
            thinking_chars=len(final_thinking),
            tool_calls=len(final_tool_calls) + (1 if final_function_call else 0),
            credits=final_usage.get("credits", 0),
        )

        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "model": body.model or model_level,
            "content": content_blocks,
            "stop_reason": _stop_reason_openai_to_anthropic(final_finish_reason, has_tools),
            "stop_sequence": None,
            "usage": {
                "input_tokens": final_usage.get("prompt_tokens", 0),
                "output_tokens": final_usage.get("completion_tokens", 0),
            },
        }

    return _anthropic_error(
        503,
        "api_error",
        "No available accounts. All accounts are exhausted, in cooldown, or inactive.",
    )


async def _handle_first_error(first: dict, account_id: int, model_level: str):
    msg = first.get("message", "upstream error")
    error_kind = classify_chat_error(msg, first.get("error_scope"))
    if error_kind == "quota":
        logbus.push("warn", "chat", "anthropic: quota exceeded (stream probe)", account_id=account_id, model=model_level)
        await pool.mark_quota_exceeded(account_id)
        return _anthropic_error(503, "api_error", "No available accounts after quota exhaustion.")
    if error_kind == "infrastructure":
        logbus.push("error", "chat", f"anthropic: infrastructure error: {msg[:200]}", account_id=account_id, model=model_level)
        return _anthropic_error(first.get("status") or 503, "api_error", msg)
    if error_kind == "model_queue":
        logbus.push("warn", "chat", f"anthropic: model queued: {msg[:200]}", account_id=account_id, model=model_level)
        return _anthropic_error(first.get("status") or 503, "api_error", msg)
    logbus.push("error", "chat", f"anthropic: upstream error: {msg[:200]}", account_id=account_id, model=model_level)
    await pool.mark_failure(account_id, msg)
    return _anthropic_error(first.get("status") or 502, "api_error", msg)


def _anthropic_sse_response(
    account_id: int,
    model_level: str,
    model: str,
    gen,
    first_event: dict,
) -> StreamingResponse:
    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    async def _chain():
        yield first_event
        async for e in gen:
            yield e

    async def event_stream():
        # --- message_start -------------------------------------------------
        yield _sse_event("message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        })

        next_index = 0
        open_block_type: str | None = None
        open_block_index = -1
        tool_fragments: dict[int, dict] = {}
        usage_totals = {"input_tokens": 0, "output_tokens": 0}
        text_chars = 0
        thinking_chars = 0
        stop_reason = "end_turn"

        def close_block() -> Optional[str]:
            nonlocal open_block_type, open_block_index
            if open_block_type is None:
                return None
            event = _sse_event("content_block_stop", {
                "type": "content_block_stop",
                "index": open_block_index,
            })
            open_block_type = None
            open_block_index = -1
            return event

        def open_block(block_type: str, block: dict) -> str:
            nonlocal open_block_type, open_block_index, next_index
            open_block_type = block_type
            open_block_index = next_index
            next_index += 1
            return _sse_event("content_block_start", {
                "type": "content_block_start",
                "index": open_block_index,
                "content_block": block,
            })

        errored = False
        try:
            async for event in _chain():
                etype = event["type"]
                if etype == "text":
                    if open_block_type != "text":
                        closed = close_block()
                        if closed:
                            yield closed
                        yield open_block("text", {"type": "text", "text": ""})
                    text_chars += len(event["text"])
                    yield _sse_event("content_block_delta", {
                        "type": "content_block_delta",
                        "index": open_block_index,
                        "delta": {"type": "text_delta", "text": event["text"]},
                    })
                elif etype == "thinking":
                    if open_block_type != "thinking":
                        closed = close_block()
                        if closed:
                            yield closed
                        yield open_block("thinking", {"type": "thinking", "thinking": ""})
                    thinking_chars += len(event["thinking"])
                    yield _sse_event("content_block_delta", {
                        "type": "content_block_delta",
                        "index": open_block_index,
                        "delta": {"type": "thinking_delta", "thinking": event["thinking"]},
                    })
                elif etype == "reasoning_signature":
                    # Qoder streams the reasoning signature separately; the
                    # Anthropic wire format carries it as a signature_delta on
                    # the open thinking block. Round-tripping it lets clients
                    # (Claude Code) preserve reasoning state across turns.
                    if open_block_type != "thinking":
                        closed = close_block()
                        if closed:
                            yield closed
                        yield open_block("thinking", {"type": "thinking", "thinking": ""})
                    yield _sse_event("content_block_delta", {
                        "type": "content_block_delta",
                        "index": open_block_index,
                        "delta": {"type": "signature_delta", "signature": event["signature"]},
                    })
                elif etype == "tool_calls":
                    _merge_tool_call_fragments(tool_fragments, event["tool_calls"])
                elif etype == "function_call":
                    fragment = event["function_call"]
                    _merge_tool_call_fragments(tool_fragments, [{
                        "id": fragment.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": fragment.get("name", ""),
                            "arguments": fragment.get("arguments", ""),
                        },
                    }])
                elif etype == "done":
                    usage = event.get("usage") or {}
                    usage_totals = {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                    }
                    has_tools = bool(tool_fragments)
                    stop_reason = _stop_reason_openai_to_anthropic(
                        event.get("finish_reason"), has_tools)

                    await pool.mark_success(
                        account_id,
                        usage.get("completion_tokens", 0),
                        usage.get("credits") or usage.get("total_credits") or 0.0,
                    )
                    logbus.push(
                        "info", "chat", "anthropic stream done",
                        account_id=account_id, model=model_level,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        thinking_chars=thinking_chars,
                        text_chars=text_chars,
                        tool_calls=len(tool_fragments),
                        finish_reason=event.get("finish_reason"),
                        credits=usage.get("credits", 0),
                    )
                elif etype == "error":
                    errored = True
                    error_kind = classify_chat_error(
                        event["message"], event.get("error_scope"))
                    if error_kind == "quota":
                        logbus.push("warn", "chat", "anthropic: quota exceeded (stream)", account_id=account_id, model=model_level)
                        await pool.mark_quota_exceeded(account_id)
                    elif error_kind in ("model_queue", "infrastructure"):
                        logbus.push("warn" if error_kind == "model_queue" else "error",
                                    "chat", f"anthropic: {error_kind} (stream): {event['message'][:200]}",
                                    account_id=account_id, model=model_level)
                    else:
                        logbus.push("error", "chat", f"anthropic: stream error: {event['message'][:200]}", account_id=account_id, model=model_level)
                        await pool.mark_failure(account_id, event["message"])
                    closed = close_block()
                    if closed:
                        yield closed
                    yield _sse_event("error", {
                        "type": "error",
                        "error": {"type": "api_error", "message": event["message"]},
                    })
        except Exception as e:  # noqa: BLE001
            errored = True
            logbus.push("error", "chat", f"anthropic: stream exception: {str(e)[:200]}", account_id=account_id, model=model_level)
            closed = close_block()
            if closed:
                yield closed
            yield _sse_event("error", {
                "type": "error",
                "error": {"type": "api_error", "message": str(e)},
            })

        # flush accumulated tool calls as tool_use blocks
        for call in _finalize_tool_calls(tool_fragments):
            closed = close_block()
            if closed:
                yield closed
            yield open_block("tool_use", {
                "type": "tool_use",
                "id": call["id"],
                "name": call["function"]["name"],
                "input": {},
            })
            yield _sse_event("content_block_delta", {
                "type": "content_block_delta",
                "index": open_block_index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": call["function"]["arguments"] or "{}",
                },
            })
            closed = close_block()
            if closed:
                yield closed

        closed = close_block()
        if closed:
            yield closed

        if not errored:
            yield _sse_event("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": usage_totals,
            })
            yield _sse_event("message_stop", {"type": "message_stop"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    """Rough token estimate — Claude Code calls this before sending."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"input_tokens": 1}
    total = 0
    for field in ("system", "messages", "tools"):
        value = body.get(field)
        if value is not None:
            try:
                total += len(json.dumps(value, ensure_ascii=False))
            except (TypeError, ValueError):
                pass
    return {"input_tokens": max(1, total // 4)}
