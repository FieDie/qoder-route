from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ── Account ──

class AccountCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    pat_token: str = Field(..., min_length=1)
    priority: int = 0
    model_level: str = "auto"
    default_model: str = ""


class AccountOut(BaseModel):
    id: int
    name: str
    pat_short: str
    is_active: bool
    is_available: bool
    priority: int
    model_level: str
    default_model: str
    last_used_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error_message: Optional[str] = None
    consecutive_failures: int
    total_requests: int
    total_tokens: int
    plan_tier: Optional[str] = None
    plan_name: Optional[str] = None
    is_paid: bool = False
    plan_end_date: Optional[float] = None
    quota_expires_at: Optional[float] = None
    email: Optional[str] = None
    quota_total: Optional[float] = None
    quota_used: Optional[float] = None
    quota_remaining: Optional[float] = None
    quota_percentage: Optional[float] = None
    quota_unit: str = "credits"
    is_quota_exceeded: bool = False
    quota_fetched_at: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountPoolStatus(BaseModel):
    total_accounts: int
    active_accounts: int
    available_accounts: int
    accounts_in_cooldown: int
    total_requests: int
    accounts: list[AccountOut]


# ── Chat ──

class ChatMessage(BaseModel):
    role: str
    content: Optional[object] = None
    tool_calls: Optional[list[dict]] = None
    function_call: Optional[dict] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    # OpenAI-compatible reasoning history used by Qoder.  These must survive
    # Pydantic validation so multi-turn chats can send the state back upstream.
    reasoning_content: Optional[str] = None
    reasoning_content_signature: Optional[str] = None
    signature: Optional[str] = None
    reasoning_item: Optional[object] = None


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: Optional[list[dict]] = None
    tool_choice: Optional[object] = None
    # Mirrors Qoder CLI /effort panel — three independent knobs:
    reasoning_effort: Optional[str] = None  # Thinking Effort: none|minimal|low|medium|high|xhigh|max (default: max)
    fast: Optional[bool] = None             # Fast mode function-switch (default: off)
    context_window: Optional[int] = None    # Context Window override, e.g. 1000000


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict]
    usage: dict


# ── Stats ──

class DashboardStats(BaseModel):
    total_accounts: int
    active_accounts: int
    available_now: int
    accounts_in_cooldown: int
    total_requests: int
    total_tokens: int
    credits_spent: float = 0.0
    accounts_by_model: dict[str, int]
    recent_errors: list[dict]
