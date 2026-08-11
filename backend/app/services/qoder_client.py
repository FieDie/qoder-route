import asyncio
import json
import logging
import os
import re
import uuid
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("qoderroute.qoder")

QODER_MODEL_LEVELS = {
    "qwen3.8-max":       "qmodel_38max",
    "qwen3.7-max":       "qmodel_latest",
    "qwen3.7-plus":      "qmodel",
    "kimi-k3":            "kmodel_latest",
    "kimi-k2.7-code":     "kmodel",
    "glm-5.2":            "gm51model",
    "deepseek-v4-pro":    "dmodel",
    "deepseek-v4-flash":  "dfmodel",
    "minimax-m3":         "mmodel",
}

QODER_MODEL_DISPLAY = [
    ("Auto", "auto"),
    ("Ultimate", "qmodel_preview"),
    ("Performance", "qmodel_latest"),
    ("Efficient", "qmodel"),
    ("Lite", "kmodel"),
    ("Cantus", "gm51model"),
    ("Qwen3.8-Max", "qmodel_38max"),
    ("Qwen3.7-Max", "qmodel_latest"),
    ("Qwen3.7-Plus", "qmodel"),
    ("Kimi-K3", "kmodel_latest"),
    ("Kimi-K2.7-Code", "kmodel"),
    ("GLM-5.2", "gm51model"),
    ("DeepSeek-V4-Pro", "dmodel"),
    ("DeepSeek-V4-Flash", "dfmodel"),
    ("MiniMax-M3", "mmodel"),
]

QODER_JOB_TOKEN_EXCHANGE_URL = "https://openapi.qoder.sh/api/v1/jobToken/exchange"

CLI_TIMEOUT_SECONDS = 300


def resolve_model_level(model: str) -> str:
    # Strip provider prefix like "qoder/deepseek-v4-flash".  Model IDs from
    # /v1/models are already Qoder level keys, so preserve them verbatim before
    # normalizing friendly display names (which turns underscores into dashes).
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    raw_key = model.strip().lower()
    known_levels = {level for _, level in QODER_MODEL_DISPLAY}
    if raw_key in known_levels:
        return raw_key

    key = raw_key.replace(" ", "-").replace("_", "-")
    if key in QODER_MODEL_LEVELS:
        return QODER_MODEL_LEVELS[key]
    for display_name, level in QODER_MODEL_DISPLAY:
        if (
            display_name.lower().replace(" ", "-") == key
            or level.lower().replace("_", "-") == key
        ):
            return level
    return "auto"


async def list_models_via_cli(pat_token: str) -> list[str]:
    try:
        env = {**os.environ}
        if pat_token:
            env["QODER_PERSONAL_ACCESS_TOKEN"] = pat_token
        proc = await asyncio.create_subprocess_exec(
            _find_qodercli(),
            "--list-models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0:
            logger.warning(f"qodercli --list-models failed: {stderr.decode()[:200]}")
            return []

        lines = stdout.decode().strip().split("\n")
        models = []
        for line in lines:
            line = line.strip()
            if line and line.upper() != "MODEL" and not line.startswith("Invalid"):
                models.append(line)
        return models
    except Exception as e:
        logger.warning(f"Failed to list models: {e}")
        return []


async def validate_pat(pat_token: str) -> tuple[bool, str]:
    models = await list_models_via_cli(pat_token)
    if models:
        return True, "Valid"
    return False, "Token validation failed — no models returned"


async def exchange_job_token(pat_token: str) -> Optional[str]:
    if not pat_token.startswith("pt-"):
        return pat_token

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                QODER_JOB_TOKEN_EXCHANGE_URL,
                json={"personal_token": pat_token},
            )
            if resp.status_code != 200:
                logger.warning(f"Job token exchange failed: {resp.status_code}")
                return pat_token

            data = resp.json()
            for key in ["job_token", "jobToken", "jt", "token"]:
                val = data.get(key) or (data.get("data") or {}).get(key)
                if val and isinstance(val, str) and val.startswith("jt-"):
                    return val

            return pat_token
    except Exception as e:
        logger.warning(f"Job token exchange error: {e}")
        return pat_token


def _flatten_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("type")
                if t in ("text", "input_text"):
                    parts.append(item.get("text", ""))
                elif t in ("image_url", "input_image"):
                    parts.append("[image]")
        return "\n".join(p for p in parts if p)
    return str(content)


def _build_prompt(messages: list[dict], tools: Optional[list[dict]] = None) -> str:
    parts = []

    if tools:
        tool_lines = []
        for tool in tools:
            fn = tool.get("function", tool)
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
            tool_lines.append(f"- {name}: {desc}\n  parameters: {json.dumps(params)}")
        parts.append(
            "You are an AI assistant with access to external tools that the CLIENT executes on your behalf.\n\n"
            "# Available tools\n" + "\n".join(tool_lines) + "\n\n"
            "# Tool call protocol (STRICT)\n"
            "To call a tool, output one or more blocks in EXACTLY this format, with no other text:\n"
            "<tool_call>{\"name\": \"<tool_name>\", \"arguments\": {<json arguments>}}</tool_call>\n"
            "Rules:\n"
            "- When calling tools, output ONLY <tool_call> blocks — no prose before or after.\n"
            "- arguments must be valid JSON matching the tool's parameters schema.\n"
            "- You may call multiple tools by emitting multiple <tool_call> blocks.\n"
            "- After the client sends back tool results, continue the task.\n"
            "- If no tool is needed, answer normally in plain text."
        )
    else:
        parts.append("You are an AI assistant. Respond to the user's messages.")

    parts.append("")
    parts.append("# Conversation transcript")

    for msg in messages:
        role = (msg.get("role") or "unknown").lower()
        if role == "tool":
            name = msg.get("name") or "tool"
            result = _flatten_content(msg.get("content"))
            parts.append(f"<tool_result name=\"{name}\">\n{result}\n</tool_result>")
            continue

        label = role.upper()
        content = _flatten_content(msg.get("content"))
        block = f"{label}:\n{content}" if content else f"{label}:"

        # assistant tool calls from history
        if role == "assistant" and msg.get("tool_calls"):
            calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                calls.append(f"<tool_call>{{\"name\": \"{fn.get('name')}\", \"arguments\": {fn.get('arguments', '{}')}}}</tool_call>")
            if calls:
                block = (block + "\n" + "\n".join(calls)).strip()

        parts.append(block)

    parts.append("")
    if tools:
        parts.append("Reply now — either with plain text, or with <tool_call> blocks only if you need a tool.")
    else:
        parts.append("Reply now with the assistant response only.")

    return "\n\n".join(parts)


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def parse_tool_calls(text: str) -> tuple[str, list[dict]]:
    """Extract <tool_call> blocks. Returns (remaining_text, openai_tool_calls)."""
    calls = []
    for m in TOOL_CALL_RE.finditer(text):
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        name = payload.get("name")
        if not name:
            continue
        args = payload.get("arguments", {})
        calls.append({
            "id": f"call_{uuid.uuid4().hex[:20]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": args if isinstance(args, str) else json.dumps(args),
            },
        })
    remaining = TOOL_CALL_RE.sub("", text).strip()
    return remaining, calls


async def stream_chat_events(
    pat_token: str,
    model_level: str,
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    """Stream events from qodercli stream-json output.

    Yields dicts:
      {"type": "text", "text": str}           — assistant text delta
      {"type": "thinking", "thinking": str}   — reasoning delta
      {"type": "done", "result": str, "usage": dict}  — final result
      {"type": "error", "message": str}       — failure
    """
    resolved_model = resolve_model_level(model_level)
    prompt = _build_prompt(messages)

    args = [
        _find_qodercli(),
        "--print",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--model", resolved_model,
        "--tools", "",
        "--no-session-persistence",
        "--config-dir", f"{settings.data_dir}/qoder-cli",
    ]

    env = {**os.environ}
    if pat_token:
        env["QODER_PERSONAL_ACCESS_TOKEN"] = pat_token

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        yield {"type": "error", "message": "qodercli not found. Install from https://qoder.com"}
        return

    try:
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass

    deadline = asyncio.get_event_loop().time() + CLI_TIMEOUT_SECONDS
    saw_result = False

    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                proc.kill()
                yield {"type": "error", "message": "qodercli timed out"}
                return

            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                proc.kill()
                yield {"type": "error", "message": "qodercli timed out"}
                return

            if not line:
                break

            try:
                event = json.loads(line.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            if etype == "stream_event":
                inner = event.get("event", {})
                inner_type = inner.get("type")

                if inner_type == "content_block_delta":
                    delta = inner.get("delta", {})
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield {"type": "text", "text": text}
                    elif delta_type == "thinking_delta":
                        thinking = delta.get("thinking", "")
                        if thinking:
                            yield {"type": "thinking", "thinking": thinking}

            elif etype == "result":
                saw_result = True
                is_error = event.get("is_error", False) or event.get("subtype") == "error"
                if is_error:
                    message = event.get("result") or event.get("error") or "Unknown error"
                    yield {"type": "error", "message": str(message)}
                else:
                    usage_raw = event.get("usage") or {}
                    prompt_tok = usage_raw.get("input_tokens", 0)
                    completion_tok = usage_raw.get("output_tokens", 0)
                    result_text = str(event.get("result", ""))
                    # Qoder reports 0 tokens and bills via credits; estimate tokens
                    # from text when the upstream reports zeros so pool accounting works.
                    if completion_tok == 0 and result_text:
                        completion_tok = max(len(result_text) // 4, 1)
                    usage = {
                        "prompt_tokens": prompt_tok,
                        "completion_tokens": completion_tok,
                        "total_tokens": prompt_tok + completion_tok,
                        "credits": event.get("total_credits") or usage_raw.get("credits") or 0,
                    }
                    yield {
                        "type": "done",
                        "result": result_text,
                        "usage": usage,
                    }
                return

        # stdout closed without a result event
        if not saw_result:
            await proc.wait()
            stderr_out = await proc.stderr.read()
            err = stderr_out.decode("utf-8", errors="replace").strip()[:500]
            rc = proc.returncode
            if rc and rc != 0:
                yield {"type": "error", "message": f"qodercli exited {rc}: {err or 'no output'}"}
            else:
                yield {"type": "error", "message": err or "qodercli closed stream without result"}

    except asyncio.CancelledError:
        proc.kill()
        raise
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


async def chat_completion(
    pat_token: str,
    model_level: str,
    messages: list[dict],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    """Non-streaming completion: consumes the event stream, returns final text + real usage."""
    final_result = ""
    final_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    text_parts: list[str] = []

    async for event in stream_chat_events(pat_token, model_level, messages):
        if event["type"] == "text":
            text_parts.append(event["text"])
        elif event["type"] == "done":
            final_result = event["result"] or "".join(text_parts)
            final_usage = event["usage"]
        elif event["type"] == "error":
            return {"text": "", "is_error": True, "error_message": event["message"], "usage": final_usage}

    if not final_result and text_parts:
        final_result = "".join(text_parts)

    return {
        "text": final_result,
        "is_error": False,
        "error_message": "",
        "usage": final_usage,
    }


def _find_qodercli() -> str:
    if settings.qodercli_path:
        return settings.qodercli_path
    import shutil
    path = shutil.which("qodercli")
    if path:
        return path
    for p in [
        os.path.expanduser("~/.local/bin/qodercli"),
        os.path.expanduser("~/.qoder/bin/qodercli/qodercli"),
        "/usr/local/bin/qodercli",
    ]:
        if os.path.exists(p):
            return p
    return "qodercli"
