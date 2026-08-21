import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import httpx

from app.services.quota_service import (
    get_job_token,
    get_uid,
    looks_like_quota_error,
    parse_model_queue,
    MODEL_QUEUE_ERROR_CODE,
)
from app.services import settings_service, signer_service
from app.services.model_catalog import MODEL_CATALOG

logger = logging.getLogger("qoderroute.direct")

SIGNER_URL = signer_service.SIGNER_URL
# Optional operator override.  Without one, use the runtime Settings choice;
# the bundled Qoder CLI endpoint cache remains a defensive fallback.
INFER_BASE = os.getenv("QODER_INFER_BASE", "").rstrip("/")
DEFAULT_INFER_BASE = "https://api3.qoder.sh"
_INFER_BASE_BY_SETTING = {
    "api1": "https://api1.qoder.sh",
    "api2": "https://api2.qoder.sh",
    "api3": "https://api3.qoder.sh",
}
INFER_ENDPOINT_CACHE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "qoder-cli"
    / ".cache"
    / "endpoint-cache.json"
)
# Machine ID per-account (set by Account model). This is the fallback when an
# old account has no machine_id yet; new accounts always get a random UUID.
_MACHINE_ID_DEFAULT = "f0aef754-0595-447d-98bd-75b6a8a68804"
QODER_INFER_USER_AGENT = "Bun/1.3.14"

_signer_client: Optional[httpx.AsyncClient] = None
_upstream_client: Optional[httpx.AsyncClient] = None


def _get_signer() -> httpx.AsyncClient:
    global _signer_client
    if _signer_client is None:
        _signer_client = httpx.AsyncClient(timeout=20)
    return _signer_client


def _get_upstream() -> httpx.AsyncClient:
    global _upstream_client
    if _upstream_client is None:
        _upstream_client = httpx.AsyncClient(
            timeout=httpx.Timeout(300, connect=20),
            limits=httpx.Limits(max_keepalive_connections=16, max_connections=32),
            http2=False,
        )
    return _upstream_client

MODEL_KEY_MAP = {
    **{str(entry["key"]): str(entry["key"]) for entry in MODEL_CATALOG},
    # Kept for callers that still use the old private preview tier.  It is not
    # advertised as Qwen3.8-Max and intentionally stays outside the catalog.
    "qmodel_preview": "qmodel_preview",
}


# Fast mode is a per-model function switch; in Qoder it's only exposed on
# Kimi K2.7 Code (our "kmodel" level) — and it's ON by default there.
_FAST_CAPABLE = {"kmodel"}

# Context window defaults used by the direct client.  ``auto`` only advertises
# 128K/180K in the Qoder 1.1.17 catalog; the named long-context models accept
# 1M, except Kimi K2.7 Code which has one fixed 256K window.
_DEFAULT_CONTEXT_WINDOW = 1_000_000
_CONTEXT_WINDOW_BY_MODEL = {
    str(entry["key"]): int(
        max(entry["context_windows"])
        if entry["context_windows"]
        else entry["max_input_tokens"]
    )
    for entry in MODEL_CATALOG
}
_DEFAULT_MAX_OUTPUT_TOKENS = 32_000
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
# Native Qoder normalizes catalog models before placing them in the request.
# Most legacy tier keys tolerate the compact form, but the final Qwen3.8
# route needs its real catalog identity instead of the old preview fallback.
_MODEL_CONFIG_DETAILS: dict[str, dict[str, Any]] = {
    str(entry["key"]): {
        "display_name": str(entry["name"]),
        "model": "",
        "format": "openai",
        "is_vl": bool(entry["is_vision"]),
        "api_key": "",
        "url": "",
        "max_input_tokens": int(entry["max_input_tokens"]),
    }
    for entry in MODEL_CATALOG
}
# Qwen3.8-Max calls its strongest catalog effort ``xhigh``.  Sending the
# generic ``max`` value used by the other models is outside its advertised
# enum and can make the inference gateway reject an otherwise valid request.
_MAX_REASONING_EFFORT_BY_MODEL = {"qmodel_38max": "xhigh"}
# Capability from Qoder's model catalog.  Kimi/Auto can emit opportunistic
# reasoning, but the CLI still declares them as non-reasoning models and uses
# parameters.enable_thinking as a separate best-effort switch.
_REASONING_CAPABLE_MODELS = {
    str(entry["key"]) for entry in MODEL_CATALOG if entry["is_reasoning"]
} | {"qmodel_preview"}


def normalize_session_id(session_id: Optional[str]) -> Optional[str]:
    """Return a safe upstream session id, or ``None`` for invalid input."""
    if not isinstance(session_id, str):
        return None
    candidate = session_id.strip()
    if not _SESSION_ID_PATTERN.fullmatch(candidate):
        return None
    return candidate


def _session_fingerprint(session_id: str) -> str:
    """A non-reversible identifier suitable for correlating router logs."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def _traceparent() -> str:
    """Create the W3C trace header injected by Qoder's native transport."""
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def _valid_infer_base(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip().rstrip("/")
    if candidate in _INFER_BASE_BY_SETTING.values():
        return candidate
    return None


def _resolve_infer_base() -> str:
    # An environment override is an operator-level policy and remains the
    # highest-precedence choice.  The DB-backed selection is read on every
    # request, so a Settings API update takes effect without a process restart.
    override = _valid_infer_base(INFER_BASE)
    if override:
        return override
    selected = _INFER_BASE_BY_SETTING.get(settings_service.get_qoder_infer_base())
    if selected:
        return selected
    try:
        cached = json.loads(INFER_ENDPOINT_CACHE.read_text(encoding="utf-8"))
        prod = ((cached.get("entries") or {}).get("prod") or {})
        candidates = [*(prod.get("inferEndpoints") or []), prod.get("endpoint")]
        for candidate in candidates:
            resolved = _valid_infer_base(candidate)
            if resolved:
                return resolved
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DEFAULT_INFER_BASE


def _normalize_effort(effort: Optional[str], model_key: str) -> str:
    """Use the strongest effort name accepted by the selected model."""
    return _MAX_REASONING_EFFORT_BY_MODEL.get(model_key, "max")


def _extract_queue_payload(text: str) -> Optional[str]:
    """Return the raw inner ``{"code":"10605",...}`` payload from a 403 body.

    Accepts both a direct queue body and the forwarded wrapper
    ``{"detail": "upstream status 403: {\\"code\\":\\"10605\\",...}"}``.
    Parsing the substring from ``{`` with json.loads (via parse_model_queue)
    keeps escaped quotes intact. The previous string-replace tricks never
    produced valid JSON: stripping ``"upstream status "`` left the ``403:``
    prefix behind, and blanket-unescaping ``\\"`` corrupted payloads whose
    own values contain quotes — so the queue payload never reached the API
    layer and the isQueued-based retry never fired.
    """
    if parse_model_queue(text) is not None:
        return text[text.index("{"):]
    parsed = _try_json(text)
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    if (
        isinstance(detail, str)
        and MODEL_QUEUE_ERROR_CODE in detail
        and "{" in detail
    ):
        inner = detail[detail.index("{"):]
        if parse_model_queue(inner) is not None:
            return inner
    return None


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") in ("text", "input_text"):
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _context_strings(messages: list[dict]) -> tuple[str, str]:
    leading_system: list[str] = []
    for message in messages:
        if message.get("role") != "system":
            break
        system_text = _text_content(message.get("content"))
        if system_text:
            leading_system.append(system_text)

    system_prompt = "\n\n".join(leading_system)
    last_user_text = ""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        # OpenCode sends image turns as a multimodal content array.  Falling
        # through to an older string-only user message makes chat_context point
        # at the previous task (observed live as "пасиб") instead of the
        # current image instruction.
        user_text = _text_content(message.get("content"))
        if user_text:
            last_user_text = user_text
            break
    return system_prompt, last_user_text


def _business_name(last_user_text: str) -> str:
    """Return the compact request label carried by Qoder CLI business data."""
    collapsed = " ".join(last_user_text.split())
    if not collapsed:
        return "OpenAI chat"
    # This field is routing/telemetry metadata, not a second copy of a large
    # prompt.  Native Qoder similarly sends a short session label here.
    return collapsed[:64]


def _prepare_messages(messages: list[dict]) -> tuple[str, list[dict], str]:
    """Mirror the native builder's system/history/chat-context split."""
    system_prompt, last_user_text = _context_strings(messages)
    first_history_index = 0
    while (
        first_history_index < len(messages)
        and messages[first_history_index].get("role") == "system"
    ):
        first_history_index += 1

    normalized = [_normalize_message(message) for message in messages[first_history_index:]]
    if system_prompt:
        normalized.insert(0, {"role": "system", "content": system_prompt})
    return system_prompt, normalized, last_user_text


def _build_body(messages: list[dict], model_key: str, tools: Optional[list[dict]],
                reasoning_effort: Optional[str] = None,
                fast: Optional[bool] = None,
                context_window: Optional[int] = None,
                max_tokens: Optional[int] = None,
                session_id: Optional[str] = None,
                tool_choice: Optional[object] = None) -> str:
    req_id = str(uuid.uuid4())
    resolved_session_id = normalize_session_id(session_id) or str(uuid.uuid4())
    effort = _normalize_effort(reasoning_effort, model_key)
    thinking_enabled = effort != "none"
    is_reasoning = model_key in _REASONING_CAPABLE_MODELS and thinking_enabled
    system_prompt, normalized_messages, last_user_text = _prepare_messages(messages)

    # fast defaults ON for capable models unless caller explicitly disables it
    if fast is None:
        fast = model_key in _FAST_CAPABLE
    # context window falls back to the per-model default
    if not context_window or context_window <= 0:
        context_window = _CONTEXT_WINDOW_BY_MODEL.get(model_key, _DEFAULT_CONTEXT_WINDOW)

    model_config: dict[str, Any] = {
        "key": model_key,
        **_MODEL_CONFIG_DETAILS.get(model_key, {}),
        "source": "system",
        "is_reasoning": is_reasoning,
    }
    if fast and model_key in _FAST_CAPABLE:
        model_config["function_switches"] = {"fast": True}

    parameters: dict[str, Any] = {
        # Native Qoder always reserves an output allowance: the caller's
        # explicit limit, or the catalog default (32K fallback in the CLI).
        "max_tokens": (
            max_tokens
            if max_tokens is not None and max_tokens > 0
            else _DEFAULT_MAX_OUTPUT_TOKENS
        ),
        # This is the field emitted by Qoder CLI. Putting the value in
        # model_config.context_window is ignored by the inference request path,
        # leaving the model on its smaller default window.  Once the prompt
        # grows into the reserved reasoning space, upstream then omits thinking.
        "context_length": context_window,
    }
    # Qwen3.8 enables thinking through its catalog default.  Its provider
    # rejects the generic explicit thinking switches even though other Qoder
    # models accept them, so mirror the native request and omit both fields.
    if model_key != "qmodel_38max":
        parameters["reasoning_effort"] = effort
        if thinking_enabled:
            # The native CLI derives the budget from reasoning_effort.  Sending
            # a separate 65K budget reserves excess output space and can squeeze
            # thinking as the input approaches the context limit.
            parameters["enable_thinking"] = True
        else:
            parameters["enable_thinking"] = False

    body: dict[str, Any] = {
        "request_id": req_id,
        "request_set_id": req_id,
        "chat_record_id": req_id,
        # OpenCode sends one stable X-Session-Id for the whole conversation.
        # Native Qoder likewise reuses its engine session id across every
        # model/tool iteration; replacing it on each HTTP request discards that
        # continuity upstream.
        "session_id": resolved_session_id,
        "stream": True,
        "chat_task": "FREE_INPUT",
        # Native Qoder includes the selected model's reasoning capability in
        # chat_context as well as model_config.  Some legacy inference paths
        # consult this copy while continuing long tool-call conversations.
        "chat_context": {
            "text": last_user_text,
            "features": [],
            "extra": {
                "context": [],
                "modelConfig": {
                    "key": model_key,
                    "is_reasoning": is_reasoning,
                },
                "originalContent": last_user_text,
            },
            "chatPrompt": "",
            "imageUrls": None,
        },
        "is_reply": True,
        "is_retry": False,
        "source": 1,
        "version": "3",
        "agent_id": "agent_common",
        "task_id": "common",
        "session_type": "qodercli",
        "aliyun_user_type": "",
        "model_config": model_config,
        "system": system_prompt,
        "messages": normalized_messages,
        "tools": [_normalize_tool(t) for t in tools] if tools else [],
        **({"tool_choice": tool_choice} if tool_choice is not None else {}),
        "parameters": parameters,
        # Native Qoder attaches this business envelope to every agent request.
        # Qwen3.8's dedicated provider route requires it; without it the
        # gateway returns `[FAIL]node:oa_qwen-plus... Execution failed: null`.
        "business": {
            "product": "cli",
            "version": "1.1.26",
            "type": "agent",
            "id": str(uuid.uuid4()),
            "name": _business_name(last_user_text),
            "begin_at": int(time.time() * 1000),
            "stage": "start",
        },
    }
    return json.dumps(body)


def _normalize_message(m: dict) -> dict:
    out: dict[str, Any] = {"role": m.get("role", "user")}
    content = m.get("content")
    embedded_reasoning: list[str] = []
    embedded_signature: Optional[str] = None
    embedded_reasoning_item: Optional[dict[str, Any]] = None
    if isinstance(content, list):
        parts = []
        for p in content:
            if not isinstance(p, dict):
                continue
            t = p.get("type")
            if t == "text":
                parts.append({"type": "text", "text": p.get("text", "")})
            elif t == "image_url":
                iu = p.get("image_url") or {}
                parts.append({"type": "image_url", "image_url": {"url": iu.get("url", "")}})
            elif t == "image":
                # AI SDK style: {type:"image", image: data-url}
                img = p.get("image", "")
                parts.append({"type": "image_url", "image_url": {"url": img}})
            elif t in ("thinking", "reasoning"):
                # Accept Anthropic/AI-SDK-style history and translate it to the
                # OpenAI-compatible fields expected by Qoder's inference API.
                reasoning = p.get("thinking") or p.get("reasoning") or p.get("text")
                if reasoning:
                    embedded_reasoning.append(str(reasoning))
                if p.get("signature"):
                    embedded_signature = str(p["signature"])
            elif t == "redacted_thinking":
                # Anthropic-style redacted thinking is the same opaque state
                # Qoder carries in reasoning_item.encrypted_content.
                encrypted = p.get("data") or p.get("encrypted_content")
                if encrypted:
                    metadata = p.get("reasoning_item")
                    embedded_reasoning_item = (
                        dict(metadata) if isinstance(metadata, dict) else {}
                    )
                    embedded_reasoning_item.pop("encrypted_content", None)
                    embedded_reasoning_item.setdefault("type", "reasoning")
                    embedded_reasoning_item["encrypted_content"] = str(encrypted)
        out["content"] = parts if parts else ""
    else:
        out["content"] = content if content is not None else ""
    if m.get("name"):
        out["name"] = m["name"]
    if m.get("role") == "assistant" and m.get("tool_calls"):
        out["tool_calls"] = [
            {
                "index": tc.get("index", i),
                "id": tc.get("id"),
                "type": "function",
                "function": {
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments"),
                },
            }
            for i, tc in enumerate(m["tool_calls"])
        ]
    if m.get("role") == "assistant" and m.get("function_call"):
        function_call = m["function_call"]
        out["function_call"] = {
            "name": function_call.get("name"),
            "arguments": function_call.get("arguments"),
        }
    if m.get("role") == "tool" and m.get("tool_call_id"):
        out["tool_call_id"] = m["tool_call_id"]

    # Qoder CLI preserves these fields across turns.  Dropping them makes a
    # long conversation lose all prior reasoning state/signatures before it is
    # sent upstream.
    reasoning_content = m.get("reasoning_content")
    if reasoning_content is None and embedded_reasoning:
        # Signatures cover the exact concatenated thinking bytes.  The native
        # converter inserts no separator between adjacent thinking blocks.
        reasoning_content = "".join(embedded_reasoning)
    if reasoning_content is not None:
        out["reasoning_content"] = reasoning_content

    reasoning_signature = m.get("reasoning_content_signature") or m.get("signature")
    if reasoning_signature is None:
        reasoning_signature = embedded_signature
    if reasoning_signature is not None:
        out["reasoning_content_signature"] = reasoning_signature

    reasoning_item = m.get("reasoning_item")
    if reasoning_item is None:
        reasoning_item = embedded_reasoning_item
    if reasoning_item is None and reasoning_content:
        # This mirrors the native CLI's history conversion.  Keeping the
        # structured summary matters when a later turn switches from plain
        # reasoning_content to the newer reasoning_item transport.
        reasoning_item = {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": reasoning_content}],
        }
    if reasoning_item is not None:
        out["reasoning_item"] = reasoning_item
    return out


def _normalize_tool(t: dict) -> dict:
    fn = t.get("function") or {}
    out: dict[str, Any] = {"type": "function", "function": {"name": fn.get("name", "")}}
    if fn.get("description"):
        out["function"]["description"] = fn["description"]
    if fn.get("parameters"):
        out["function"]["parameters"] = fn["parameters"]
    return out


async def run_infer(
    pat: str,
    model_level: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    reasoning_effort: Optional[str] = None,
    fast: Optional[bool] = None,
    context_window: Optional[int] = None,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    tool_choice: Optional[object] = None,
) -> AsyncGenerator[dict, None]:
    """Direct signed infer request. Yields events:
    {"type":"text"|"thinking"|"reasoning_item"|"reasoning_signature"|
            "tool_calls"|"function_call"|"done"|"error", ...}"""
    model_key = MODEL_KEY_MAP.get(model_level, "auto")

    jt = await get_job_token(pat)
    if not jt:
        yield {"type": "error", "message": "job token exchange failed"}
        return
    uid = await get_uid(pat)
    if not uid:
        yield {"type": "error", "message": "userinfo fetch failed"}
        return

    supplied_session_id = normalize_session_id(session_id)
    resolved_session_id = supplied_session_id or str(uuid.uuid4())
    # Use per-account machine_id when provided, else default (for backwards compat)
    effective_machine_id = machine_id or _MACHINE_ID_DEFAULT
    body_json = _build_body(
        messages,
        model_key,
        tools,
        reasoning_effort,
        fast,
        context_window,
        max_tokens,
        resolved_session_id,
        tool_choice=tool_choice,
    )
    request_system_prompt, request_chat_context = _context_strings(messages)
    effective_effort = _normalize_effort(reasoning_effort, model_key)
    infer_base = _resolve_infer_base()

    try:
        client = _get_signer()
        r = await signer_service.post_to_signer(
            "/infer",
            client=client,
            json={
                "jt": jt,
                "uid": uid,
                "machine_id": effective_machine_id,
                "base_url": infer_base,
                "body_json": body_json,
                "model_key": model_key,
                "model_source": "system",
            },
        )
        if r.status_code != 200:
            yield {
                "type": "error",
                "message": f"signer error: {r.text[:200]}",
                "status": 503,
                "error_scope": "infrastructure",
            }
            return
        signed = r.json()
        if not isinstance(signed, dict):
            raise ValueError("signer returned a non-object response")
        signed_body = signed.get("body_b64")
        headers = signed.get("headers")
        url = signed.get("url")
        if not isinstance(signed_body, str) or not isinstance(headers, dict):
            raise ValueError("signer response is missing body or headers")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ValueError("signer response contains an invalid URL")
        # qoder-server-request injects these identity headers after the WASM
        # signer returns.  The first two normally already exist; MachineOS is
        # transport-owned and therefore must be supplied here explicitly.
        headers.setdefault("Cosy-Version", "1.1.26")
        headers.setdefault("Cosy-ClientType", "5")
        headers.setdefault("Cosy-MachineOS", "x86_64_linux")
        headers.setdefault("User-Agent", QODER_INFER_USER_AGENT)
        headers.setdefault("traceparent", _traceparent())
        body_bytes = base64.b64decode(signed_body, validate=True)
    except Exception as e:
        yield {
            "type": "error",
            "message": f"signer unavailable: {e}",
            "status": 503,
            "error_scope": "infrastructure",
        }
        return

    usage: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {
        "upstream_sse_events": 0,
        "upstream_choice_chunks": 0,
        "upstream_empty_choices": 0,
        "upstream_empty_payloads": 0,
        "upstream_unhandled_choices": 0,
        "upstream_tool_call_chunks": 0,
        "upstream_tool_call_entries": 0,
        "upstream_function_call_chunks": 0,
        "upstream_payload_keys": set(),
        "upstream_unknown_string_chars": {},
        "upstream_finish_reasons": set(),
        "upstream_last_finish_reason": "",
        "request_message_count": len(messages),
        "request_reasoning_messages": sum(
            1 for message in messages if message.get("reasoning_content")
        ),
        "request_reasoning_items": sum(
            1 for message in messages if message.get("reasoning_item") is not None
        ),
        "request_context_length": (
            context_window
            if context_window is not None and context_window > 0
            else _CONTEXT_WINDOW_BY_MODEL.get(model_key, _DEFAULT_CONTEXT_WINDOW)
        ),
        "request_max_tokens": (
            max_tokens
            if max_tokens is not None and max_tokens > 0
            else _DEFAULT_MAX_OUTPUT_TOKENS
        ),
        "request_model_is_reasoning": (
            model_key in _REASONING_CAPABLE_MODELS and effective_effort != "none"
        ),
        "request_enable_thinking": effective_effort != "none",
        "request_reasoning_effort": effective_effort,
        "request_session_source": "client" if supplied_session_id else "generated",
        "request_session_fingerprint": _session_fingerprint(resolved_session_id),
        "request_system_chars": len(request_system_prompt),
        "request_chat_context_chars": len(request_chat_context),
        "request_infer_base": infer_base,
    }

    async def _decrypt(payload: str) -> Optional[str]:
        try:
            r = await signer_service.post_to_signer(
                "/decrypt",
                client=_get_signer(),
                json={"payload": payload},
            )
            return r.json().get("plain")
        except Exception:
            return None

    async def _decode_sse_event(lines: list[str]) -> tuple[list[dict], bool, bool]:
        events: list[dict] = []
        saw_done = False
        saw_finish = False
        for line in lines:
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            if payload == "[DONE]":
                saw_done = True
                continue

            data = _try_json(payload)
            if data is None:
                plain = await _decrypt(payload)
                if plain:
                    data = _try_json(plain)
            if data is None:
                continue

            inner = data.get("body")
            wrapper_status = data.get("statusCodeValue")
            if isinstance(wrapper_status, (int, float)) and int(wrapper_status) != 200:
                wrapper_message = data.get("message")
                if isinstance(inner, str):
                    decoded_inner = _try_json(inner)
                    if isinstance(decoded_inner, dict):
                        wrapper_message = decoded_inner.get("message") or wrapper_message
                        decoded_error = decoded_inner.get("error")
                        if isinstance(decoded_error, dict):
                            wrapper_message = decoded_error.get("message") or wrapper_message
                    if not wrapper_message:
                        wrapper_message = inner
                elif isinstance(inner, dict):
                    wrapper_message = inner.get("message") or wrapper_message
                    inner_error = inner.get("error")
                    if isinstance(inner_error, dict):
                        wrapper_message = inner_error.get("message") or wrapper_message
                    if not wrapper_message:
                        wrapper_message = json.dumps(inner, separators=(",", ":"))
                error_event = {
                    "type": "error",
                    "status": int(wrapper_status),
                    "message": (
                        f"upstream status {int(wrapper_status)}"
                        + (f": {wrapper_message}" if wrapper_message else "")
                    )[:512],
                }
                if looks_like_quota_error(error_event["message"]):
                    error_event["error_scope"] = "quota"
                events.append(error_event)
                continue

            if isinstance(inner, str):
                data = _try_json(inner) or {}
            elif isinstance(inner, dict):
                data = inner

            upstream_error = data.get("error")
            if upstream_error is not None:
                if isinstance(upstream_error, dict):
                    message = (
                        upstream_error.get("message")
                        or upstream_error.get("code")
                        or json.dumps(upstream_error)
                    )
                else:
                    message = str(upstream_error)
                events.append({"type": "error", "message": str(message)[:512]})
                continue

            diagnostics["upstream_sse_events"] += 1
            event_usage = data.get("usage")
            if isinstance(event_usage, dict):
                usage.update(event_usage)

            if not isinstance(data.get("choices"), list):
                continue

            diagnostics["upstream_choice_chunks"] += len(data["choices"])
            if not data["choices"]:
                diagnostics["upstream_empty_choices"] += 1

            saw_finish = saw_finish or any(
                isinstance(choice, dict) and choice.get("finish_reason") is not None
                for choice in data["choices"]
            )
            for choice in data["choices"]:
                if isinstance(choice, dict) and choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                    diagnostics["upstream_finish_reasons"].add(finish_reason)
                    diagnostics["upstream_last_finish_reason"] = finish_reason

            async for event in _emit_chunk(data, usage, diagnostics):
                events.append(event)
        return events, saw_done, saw_finish

    try:
        client = _get_upstream()
        async with client.stream("POST", url, headers=headers, content=body_bytes) as resp:
            if resp.status_code == 403:
                # Check for queue error (10605) in the response body
                text = (await resp.aread()).decode("utf-8", "replace")[:1000]

                # Yield the INNER 10605 payload (not the wrapper) so the API
                # layer's parse_model_queue can read isQueued and trigger the
                # quiet retry instead of surfacing a 503 to the client.
                queue_payload = _extract_queue_payload(text)
                if queue_payload is not None or "10605" in text.lower():
                    msg = f"model queued (10605): {(queue_payload or text)[:500]}"
                    yield {"type": "error", "status": 403, "message": msg}
                    return

                # Any other 403 is an upstream error
                message = f"upstream HTTP 403: {text}"
                event = {"type": "error", "status": 403, "message": message}
                if looks_like_quota_error(message):
                    event["error_scope"] = "quota"
                yield event
                return
            elif resp.status_code != 200:
                text = (await resp.aread()).decode("utf-8", "replace")[:500]
                yield {"type": "error", "status": resp.status_code, "message": f"upstream HTTP {resp.status_code}: {text}"}
                return

            # aiter_lines handles both LF and CRLF SSE framing.  Processing the
            # remaining frame after EOF also avoids silently dropping the last
            # reasoning/signature chunk when the server closes without a final
            # blank line.
            event_lines: list[str] = []
            stream_terminal = False
            stream_failed = False
            try:
                async for line in resp.aiter_lines():
                    if line:
                        event_lines.append(line)
                        continue

                    events, saw_done, saw_finish = await _decode_sse_event(event_lines)
                    event_lines = []
                    stream_terminal = stream_terminal or saw_done or saw_finish
                    for event in events:
                        stream_failed = stream_failed or event.get("type") == "error"
                        yield event
                    if saw_done:
                        break
                else:
                    if event_lines:
                        events, saw_done, saw_finish = await _decode_sse_event(event_lines)
                        stream_terminal = stream_terminal or saw_done or saw_finish
                        for event in events:
                            stream_failed = stream_failed or event.get("type") == "error"
                            yield event
            except Exception as e:
                # Connection dropped mid-stream - report error without waiting full timeout
                stream_failed = True
                yield {
                    "type": "error",
                    "message": f"stream interrupted: {str(e)[:500]}",
                    "status": 502,
                }
                return
            
            if stream_failed:
                return
            if not stream_terminal:
                # Truncated stream is an upstream/local transport failure, not
                # an account problem — scope it so classify_chat_error never
                # parks a healthy account for it.
                yield {
                    "type": "error",
                    "message": "upstream stream ended before [DONE] or finish_reason",
                    "error_scope": "infrastructure",
                }
                return
    except Exception as e:
        yield {"type": "error", "message": str(e)[:512]}
        return

    yield {
        "type": "done",
        "usage": usage,
        "diagnostics": _serialize_diagnostics(diagnostics),
        "finish_reason": diagnostics["upstream_last_finish_reason"] or None,
    }


def _try_json(s: str) -> Optional[dict]:
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _serialize_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    result = dict(diagnostics)
    result["upstream_payload_keys"] = ",".join(
        sorted(diagnostics["upstream_payload_keys"])
    )
    result["upstream_finish_reasons"] = ",".join(
        sorted(diagnostics["upstream_finish_reasons"])
    )
    result["upstream_unknown_string_chars"] = ",".join(
        f"{key}:{value}"
        for key, value in sorted(diagnostics["upstream_unknown_string_chars"].items())
    )
    return result


async def _emit_chunk(
    data: dict,
    usage: dict,
    diagnostics: Optional[dict[str, Any]] = None,
) -> AsyncGenerator[dict, None]:
    u = data.get("usage")
    if isinstance(u, dict):
        usage.update(u)

    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue

        # Qoder uses delta for normal streaming chunks and message for some
        # completed/legacy chunks.  Both carry the same reasoning fields.
        payload = choice.get("delta")
        if not isinstance(payload, dict) or not payload:
            payload = choice.get("message")
        if not isinstance(payload, dict):
            if diagnostics is not None:
                diagnostics["upstream_empty_payloads"] += 1
            continue

        if diagnostics is not None:
            diagnostics["upstream_payload_keys"].update(str(key) for key in payload)

        handled = False

        reasoning_content = payload.get("reasoning_content")
        if not isinstance(reasoning_content, str) or not reasoning_content:
            for alias in ("reasoning", "thinking", "analysis"):
                candidate = payload.get(alias)
                if isinstance(candidate, str) and candidate:
                    reasoning_content = candidate
                    break
        has_reasoning_content = isinstance(reasoning_content, str) and bool(reasoning_content)
        if has_reasoning_content:
            handled = True
            yield {"type": "thinking", "thinking": reasoning_content}

        reasoning_item = payload.get("reasoning_item")
        if isinstance(reasoning_item, dict):
            handled = True
            # Some transports put the visible reasoning only in summary and
            # the resumable state in encrypted_content.  Preserve both.
            if not has_reasoning_content:
                summary = _reasoning_summary_text(reasoning_item)
                if summary:
                    yield {"type": "thinking", "thinking": summary}
            yield {"type": "reasoning_item", "reasoning_item": reasoning_item}

        signature = payload.get("signature") or payload.get("reasoning_content_signature")
        if isinstance(signature, str) and signature:
            handled = True
            yield {"type": "reasoning_signature", "signature": signature}

        content = payload.get("content")
        if isinstance(content, str) and content:
            handled = True
            yield {"type": "text", "text": content}
        if payload.get("tool_calls"):
            handled = True
            if diagnostics is not None:
                diagnostics["upstream_tool_call_chunks"] += 1
                diagnostics["upstream_tool_call_entries"] += len(payload["tool_calls"])
            yield {"type": "tool_calls", "tool_calls": payload["tool_calls"]}

        function_call = payload.get("function_call")
        if isinstance(function_call, dict):
            handled = True
            if diagnostics is not None:
                diagnostics["upstream_function_call_chunks"] += 1
            yield {"type": "function_call", "function_call": function_call}

        if diagnostics is not None:
            known_fields = {
                "role",
                "content",
                "reasoning_content",
                "reasoning",
                "thinking",
                "analysis",
                "reasoning_item",
                "signature",
                "reasoning_content_signature",
                "tool_calls",
                "function_call",
            }
            for key, value in payload.items():
                if key not in known_fields and isinstance(value, str) and value:
                    counts = diagnostics["upstream_unknown_string_chars"]
                    counts[key] = counts.get(key, 0) + len(value)
            if not handled and any(
                key != "role" and value not in (None, "", [], {})
                for key, value in payload.items()
            ):
                diagnostics["upstream_unhandled_choices"] += 1


def _reasoning_summary_text(reasoning_item: dict) -> str:
    summary = reasoning_item.get("summary")
    if isinstance(summary, str):
        return summary
    if not isinstance(summary, list):
        return ""

    parts: list[str] = []
    for item in summary:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)
