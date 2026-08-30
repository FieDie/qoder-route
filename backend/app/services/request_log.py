"""Structured request tracing for the log bus + Requests view."""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from app.services import logbus, request_store
from app.services.quota_service import looks_like_rate_limit


def log_outcome(kind: str, message: str = "") -> str:
    """Map classify_chat_error() onto the compact log outcome vocabulary."""
    if kind == "infrastructure":
        return "rate_limit" if looks_like_rate_limit(message) else "infra"
    if kind == "model_queue":
        return "queue"
    return kind


class RequestTrace:
    """One client call. Threaded through every chat/anthropic log line."""

    def __init__(self, dialect: str, model: str):
        self.request_id = uuid.uuid4().hex[:12]
        self.dialect = dialect
        self.model = model
        self.started = time.time()
        self.first_token_at: Optional[float] = None
        self.account_id: Optional[int] = None
        self.account_name: Optional[str] = None

    def set_account(self, account: Any) -> None:
        self.account_id = getattr(account, "id", None)
        name = getattr(account, "name", None)
        if isinstance(name, str):
            name = name.strip() or None
        self.account_name = name or (
            f"#{self.account_id}" if self.account_id is not None else None
        )

    def mark_first_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.time()

    def emit(
        self,
        level: str,
        message: str,
        *,
        phase: str,
        outcome: Optional[str] = None,
        **extra: Any,
    ) -> dict:
        now = time.time()
        fields: dict[str, Any] = {
            "request_id": self.request_id,
            "dialect": self.dialect,
            "model": self.model,
            "phase": phase,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "outcome": outcome,
            "latency_ms": int((now - self.started) * 1000),
        }
        if self.first_token_at is not None:
            fields["first_token_ms"] = int((self.first_token_at - self.started) * 1000)
        for key, value in extra.items():
            if value is not None:
                fields[key] = value
        evt = logbus.push(level, "chat", message, **fields)
        if phase in ("done", "error"):
            request_store.schedule(evt)
        return evt
