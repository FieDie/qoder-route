import json
import os
from typing import Optional

from app.core.config import settings
from app.services.model_catalog import MODEL_CATALOG


def _model_slug(value: str) -> str:
    return value.lower().replace(" ", "-").replace("_", "-")


QODER_MODEL_DISPLAY = [
    (str(entry["name"]), str(entry["key"])) for entry in MODEL_CATALOG
]
QODER_MODEL_LEVELS = {
    _model_slug(str(entry["name"])): str(entry["key"])
    for entry in MODEL_CATALOG
}
# Keep the unversioned public aliases accepted after display names gain the
# upstream build suffix.  OpenCode model IDs intentionally remain stable.
QODER_MODEL_LEVELS.update({
    "deepseek-v4-pro": "dmodel",
    "deepseek-v4-flash": "dfmodel",
    "qwen3.8-flash": "qfmodel",
    "glm-5.3-flash": "gfmodel",
    # Retired GLM-5.2 key; keep old clients on the remaining GLM route.
    "glm-5.2": "gmodel",
    "gm51model": "gmodel",
})
# Private compatibility key previously advertised for the preview tier.  It
# is deliberately absent from the public catalog, but existing clients that
# send the exact ID must keep reaching it instead of silently falling to auto.
_LEGACY_MODEL_LEVELS = frozenset({"qmodel_preview"})


def resolve_model_level(model: str) -> str:
    # Strip provider prefix like "qoder/deepseek-v4-flash".  Model IDs from
    # /v1/models are already Qoder level keys, so preserve them verbatim before
    # normalizing friendly display names (which turns underscores into dashes).
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    raw_key = model.strip().lower()
    known_levels = {level for _, level in QODER_MODEL_DISPLAY} | _LEGACY_MODEL_LEVELS
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


async def validate_pat(pat_token: str) -> tuple[bool, str]:
    """Lightweight PAT check over HTTP: job-token exchange + userinfo.

    No qodercli dependency — a PAT is valid when the exchange yields a token
    and userinfo answers with an account id."""
    from app.services import quota_service
    try:
        uid = await quota_service.get_uid(pat_token)
    except Exception:
        uid = None
    if uid:
        return True, "Valid"
    return False, "token validation failed — no uid from userinfo"


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
