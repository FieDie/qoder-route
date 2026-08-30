"""Canonical Qoder model catalog used by routing, UI and public APIs.

Credit factors and capabilities mirror the current Qoder catalog-v6. They are
multipliers, not fixed per-request prices; upstream billing and request shape
can change the final credit charge reported by upstream.
"""
from __future__ import annotations

from typing import Any


MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {"key": "auto", "name": "Auto", "credit_factor": 1.0, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "kind": "tier"},
    {"key": "ultimate", "name": "Ultimate", "credit_factor": 1.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "tier"},
    {"key": "performance", "name": "Performance", "credit_factor": 1.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [272_000, 400_000, 1_000_000], "kind": "tier"},
    {"key": "efficient", "name": "Efficient", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "kind": "tier"},
    {"key": "lite", "name": "Lite", "credit_factor": 0.0, "is_reasoning": False, "is_vision": False, "max_input_tokens": 180_000, "context_windows": [], "kind": "tier"},
    {"key": "cmodel", "name": "Cantus", "credit_factor": 3.2, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "qmodel_38max", "name": "Qwen3.8-Max", "credit_factor": 0.5, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "qfmodel", "name": "Qwen3.8-Flash", "credit_factor": 0.1, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "qmodel_latest", "name": "Qwen3.7-Max", "credit_factor": 0.5, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "qmodel", "name": "Qwen3.7-Plus", "credit_factor": 0.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "kmodel_latest", "name": "Kimi-K3", "credit_factor": 0.8, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "kmodel", "name": "Kimi-K2.7-Code", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 256_000, "context_windows": [256_000], "kind": "model"},
    {"key": "gmodel", "name": "GLM-5.3", "credit_factor": 0.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "gfmodel", "name": "GLM-5.3-Flash", "credit_factor": 0.05, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "dmodel", "name": "DeepSeek-V4-Pro", "credit_factor": 0.8, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "dfmodel", "name": "DeepSeek-V4-Flash", "credit_factor": 0.3, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
    {"key": "mmodel", "name": "MiniMax-M3", "credit_factor": 0.2, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "kind": "model"},
)

MODEL_BY_KEY = {entry["key"]: entry for entry in MODEL_CATALOG}
MODEL_KEYS = frozenset(MODEL_BY_KEY)

# Qoder exposes this independently from ``is_reasoning``.  A model such as
# Kimi-K3 is catalogued as non-reasoning while still offering a controllable
# thinking mode.  Keeping the two flags separate prevents the UI from implying
# that Kimi cannot emit thinking blocks.
THINKING_CONFIG_BY_MODEL: dict[str, dict[str, Any]] = {
    "ultimate": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high"},
    "performance": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "medium"},
    "cmodel": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high"},
    "qmodel_38max": {"efforts": ["low", "medium", "xhigh"], "default_effort": "xhigh"},
    "qfmodel": {"efforts": ["low", "medium", "xhigh"], "default_effort": "xhigh"},
    "qmodel_latest": {"efforts": [], "default_effort": None},
    "qmodel": {"efforts": [], "default_effort": None},
    "kmodel_latest": {"efforts": ["low", "high", "max"], "default_effort": "max"},
    "gmodel": {"efforts": ["low", "high", "max"], "default_effort": "max"},
    "gfmodel": {"efforts": ["high", "max"], "default_effort": "max"},
    "dmodel": {"efforts": ["high", "max"], "default_effort": "max"},
    "dfmodel": {"efforts": ["low", "high", "max"], "default_effort": "max"},
}


def context_length_of(entry: dict[str, Any]) -> int:
    """Largest advertised context window, else the catalog max_input_tokens."""
    windows = entry.get("context_windows") or []
    if windows:
        return int(max(windows))
    return int(entry["max_input_tokens"])


def public_model_catalog() -> list[dict[str, Any]]:
    """Return detached JSON-safe rows so callers cannot mutate constants."""
    rows: list[dict[str, Any]] = []
    for entry in MODEL_CATALOG:
        thinking = THINKING_CONFIG_BY_MODEL.get(str(entry["key"]))
        row = {
            key: list(value) if isinstance(value, list) else value
            for key, value in entry.items()
        }
        row["context_length"] = context_length_of(entry)
        row["supports_thinking"] = thinking is not None
        row["thinking_efforts"] = list(thinking["efforts"]) if thinking else []
        row["default_thinking_effort"] = (
            thinking["default_effort"] if thinking else None
        )
        rows.append(row)
    return rows
