"""Canonical Qoder model catalog used by routing, UI and health probes.

Credit factors and capabilities mirror the current Qoder catalog-v6.  They
are multipliers, not fixed per-request prices; promotions and request shape
can change the final credit charge reported by upstream.
"""
from __future__ import annotations

from typing import Any


MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {"key": "auto", "name": "Auto", "credit_factor": 1.0, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "ultimate", "name": "Ultimate", "credit_factor": 1.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": False, "kind": "tier"},
    {"key": "performance", "name": "Performance", "credit_factor": 1.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [272_000, 400_000, 1_000_000], "probe_default": False, "kind": "tier"},
    {"key": "efficient", "name": "Efficient", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "lite", "name": "Lite", "credit_factor": 0.0, "is_reasoning": False, "is_vision": False, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "cmodel", "name": "Cantus", "credit_factor": 3.2, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": False, "kind": "model"},
    {"key": "qmodel_38max", "name": "Qwen3.8-Max", "credit_factor": 0.5, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "qmodel_latest", "name": "Qwen3.7-Max", "credit_factor": 0.5, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "qmodel", "name": "Qwen3.7-Plus", "credit_factor": 0.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "kmodel_latest", "name": "Kimi-K3", "credit_factor": 0.8, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "kmodel", "name": "Kimi-K2.7-Code", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 256_000, "context_windows": [256_000], "probe_default": True, "kind": "model"},
    {"key": "gm51model", "name": "GLM-5.2", "credit_factor": 0.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "dmodel", "name": "DeepSeek V4 Pro 0813", "credit_factor": 0.5, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "dfmodel", "name": "DeepSeek V4 Flash 0731", "credit_factor": 0.1, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "mmodel", "name": "MiniMax-M3", "credit_factor": 0.2, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
)

MODEL_BY_KEY = {entry["key"]: entry for entry in MODEL_CATALOG}
MODEL_KEYS_IN_ORDER = tuple(str(entry["key"]) for entry in MODEL_CATALOG)
MODEL_KEYS = frozenset(MODEL_BY_KEY)
DEFAULT_PROBE_MODEL_KEYS = tuple(
    entry["key"] for entry in MODEL_CATALOG if entry["probe_default"]
)

# Qoder exposes this independently from ``is_reasoning``.  A model such as
# Kimi-K3 is catalogued as non-reasoning while still offering a controllable
# thinking mode.  Keeping the two flags separate prevents the UI from implying
# that Kimi cannot emit thinking blocks.
THINKING_CONFIG_BY_MODEL: dict[str, dict[str, Any]] = {
    "ultimate": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high"},
    "performance": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "medium"},
    "cmodel": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high"},
    "qmodel_38max": {"efforts": ["low", "medium", "xhigh"], "default_effort": "xhigh"},
    "qmodel_latest": {"efforts": [], "default_effort": None},
    "qmodel": {"efforts": [], "default_effort": None},
    "kmodel_latest": {"efforts": ["low", "high", "max"], "default_effort": "max"},
    "gm51model": {"efforts": ["high", "max"], "default_effort": "max"},
    "dmodel": {"efforts": ["high", "max"], "default_effort": "max"},
    "dfmodel": {"efforts": ["low", "high", "max"], "default_effort": "max"},
}


def public_model_catalog() -> list[dict[str, Any]]:
    """Return detached JSON-safe rows so callers cannot mutate constants."""
    rows: list[dict[str, Any]] = []
    for entry in MODEL_CATALOG:
        thinking = THINKING_CONFIG_BY_MODEL.get(str(entry["key"]))
        row = {
            key: list(value) if isinstance(value, list) else value
            for key, value in entry.items()
            if key != "probe_default"
        }
        row["supports_thinking"] = thinking is not None
        row["thinking_efforts"] = list(thinking["efforts"]) if thinking else []
        row["default_thinking_effort"] = (
            thinking["default_effort"] if thinking else None
        )
        rows.append(row)
    return rows
