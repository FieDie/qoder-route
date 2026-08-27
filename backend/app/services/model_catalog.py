"""Canonical Qoder model catalog used by routing, UI and health probes.

Credit factors and capabilities mirror Qoder's catalog.  They are multipliers,
not fixed per-request prices; upstream billing and request shape can change
the final credit charge reported by upstream.
"""
from __future__ import annotations

from typing import Any


MODEL_CATALOG: tuple[dict[str, Any], ...] = (
# NOTE: Qoder runs night-time promotions (22:00–08:00 UTC+8) that discount
# some tiers (e.g. Qwen3.8-Max −50%, Qwen3.7-Max −80%, Qwen3.7-Plus −60%).
# The factors below are the STANDARD prices; POST /api/models/sync mirrors
# whatever promotion is currently active into the runtime catalog.
    {"key": "auto", "name": "Auto", "credit_factor": 1.0, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "ultimate", "name": "Ultimate", "credit_factor": 1.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": False, "kind": "tier"},
    {"key": "performance", "name": "Performance", "credit_factor": 1.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [272_000, 400_000, 1_000_000], "probe_default": False, "kind": "tier"},
    {"key": "efficient", "name": "Efficient", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "lite", "name": "Lite", "credit_factor": 0.0, "is_reasoning": False, "is_vision": False, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "tier"},
    {"key": "cmodel", "name": "Cantus", "credit_factor": 3.2, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": False, "kind": "model"},
    {"key": "qmodel_38max", "name": "Qwen3.8-Max", "credit_factor": 0.5, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "qfmodel", "name": "Qwen3.8-Flash", "credit_factor": 0.1, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [], "probe_default": False, "kind": "model"},
    {"key": "qmodel_latest", "name": "Qwen3.7-Max", "credit_factor": 0.5, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "qmodel", "name": "Qwen3.7-Plus", "credit_factor": 0.1, "is_reasoning": False, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "kmodel_latest", "name": "Kimi-K3", "credit_factor": 0.8, "is_reasoning": False, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "kmodel", "name": "Kimi-K2.7-Code", "credit_factor": 0.3, "is_reasoning": False, "is_vision": True, "max_input_tokens": 256_000, "context_windows": [256_000], "probe_default": True, "kind": "model"},
    {"key": "gmodel", "name": "GLM-5.3", "credit_factor": 0.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 180_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "gfmodel", "name": "GLM-5.3-Flash", "credit_factor": 0.05, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [], "probe_default": False, "kind": "model"},
    {"key": "gm51model", "name": "GLM-5.2", "credit_factor": 0.6, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "dmodel", "name": "DeepSeek-V4-Pro", "credit_factor": 0.8, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
    {"key": "dfmodel", "name": "DeepSeek-V4-Flash", "credit_factor": 0.3, "is_reasoning": True, "is_vision": True, "max_input_tokens": 1_000_000, "context_windows": [200_000, 400_000, 1_000_000], "probe_default": True, "kind": "model"},
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
    "qmodel_38max": {"efforts": ["xhigh", "low", "medium"], "default_effort": "xhigh"},
    "qfmodel": {"efforts": ["xhigh", "low", "medium"], "default_effort": "xhigh"},
    "gfmodel": {"efforts": ["high", "max"], "default_effort": "max"},
    "qmodel_latest": {"efforts": [], "default_effort": None},
    "qmodel": {"efforts": [], "default_effort": None},
    "kmodel_latest": {"efforts": ["low", "high", "max"], "default_effort": "max"},
    "gmodel": {"efforts": ["low", "high", "max"], "default_effort": "max"},
    "gm51model": {"efforts": ["high", "max"], "default_effort": "max"},
    "dmodel": {"efforts": ["high", "max"], "default_effort": "max"},
    "dfmodel": {"efforts": ["low", "high", "max"], "default_effort": "max"},
}


def public_model_catalog() -> list[dict[str, Any]]:
    """Return detached JSON-safe rows so callers cannot mutate constants."""
    rows: list[dict[str, Any]] = []
    for entry in effective_catalog():
        synced_efforts = entry.get("thinking_efforts")
        if synced_efforts is not None:
            # Synced rows carry upstream truth (order + defaults included).
            efforts = list(synced_efforts)
            default_effort = entry.get("default_thinking_effort")
        else:
            cfg = THINKING_CONFIG_BY_MODEL.get(str(entry["key"]))
            efforts = list(cfg["efforts"]) if cfg else []
            default_effort = cfg["default_effort"] if cfg else None
        row = {
            key: list(value) if isinstance(value, list) else value
            for key, value in entry.items()
            if key not in ("probe_default", "thinking_efforts", "default_thinking_effort")
        }
        row["supports_thinking"] = bool(efforts) or bool(entry.get("thinking_enabled"))
        row["thinking_efforts"] = efforts
        row["default_thinking_effort"] = default_effort
        rows.append(row)
    return rows


# ── Runtime sync layer ─────────────────────────────────────────────────────
# The upstream catalog is dynamic: price factors follow promotions (e.g.
# 22:00–08:00 UTC+8 night discounts) and new models appear without a client
# release.  services/model_sync.py fetches the live list through the signer
# (/sign_get) and installs the merged snapshot here; the static table above
# stays as the offline baseline and is used verbatim until a sync happens.

_dynamic_entries: tuple[dict[str, Any], ...] | None = None


def apply_dynamic_catalog(entries: list[dict[str, Any]]) -> None:
    """Install a synced catalog snapshot (baseline-merged, validated rows)."""
    global _dynamic_entries
    _dynamic_entries = tuple(entries)


def clear_dynamic_catalog() -> None:
    global _dynamic_entries
    _dynamic_entries = None


def effective_catalog() -> tuple[dict[str, Any], ...]:
    """Entries currently serving traffic: synced snapshot or the baseline."""
    return _dynamic_entries if _dynamic_entries is not None else MODEL_CATALOG


def model_keys() -> frozenset:
    return frozenset(str(entry["key"]) for entry in effective_catalog())


def model_keys_in_order() -> tuple[str, ...]:
    return tuple(str(entry["key"]) for entry in effective_catalog())
