import uuid

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from sqlalchemy.sql import func
from app.core.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    pat_token = Column(Text, nullable=False, unique=True)
    pat_short = Column(String(32), nullable=False)

    # Unique machine identity per account (UUID for anti-fraud).
    # Nullable for backwards compat; backfilled at startup for legacy rows.
    machine_id = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))

    # Always true — per-account disable was removed; kept for pool filters / legacy rows.
    is_active = Column(Boolean, default=True, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    priority = Column(Integer, default=0, nullable=False)

    model_level = Column(String(64), default="auto", nullable=False)
    default_model = Column(String(64), default="", nullable=False)

    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    cooldown_until = Column(DateTime(timezone=True), nullable=True)

    total_requests = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)

    plan_tier = Column(String(64), nullable=True)
    plan_name = Column(String(64), nullable=True)
    is_paid = Column(Boolean, default=False, nullable=False)
    plan_end_date = Column(Float, nullable=True)

    email = Column(String(128), nullable=True)

    quota_total = Column(Float, nullable=True)
    quota_used = Column(Float, nullable=True)
    quota_remaining = Column(Float, nullable=True)
    quota_percentage = Column(Float, nullable=True)
    quota_unit = Column(String(16), default="credits", nullable=False)
    is_quota_exceeded = Column(Boolean, default=False, nullable=False)
    quota_expires_at = Column(Float, nullable=True)
    quota_fetched_at = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
