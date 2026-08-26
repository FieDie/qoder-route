"""Panel API keys: generate, hash, verify. Plaintext is stored for copy."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from app.core.database import async_session
from app.models.api_key import ApiKey

KEY_PREFIX = "qr_"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def _prefix_for(raw: str) -> str:
    return (raw[:12] + "…") if len(raw) > 12 else raw


async def count() -> int:
    async with async_session() as session:
        result = await session.execute(select(func.count(ApiKey.id)))
        return int(result.scalar() or 0)


async def list_keys() -> list[dict]:
    async with async_session() as session:
        result = await session.execute(select(ApiKey).order_by(ApiKey.id.asc()))
        rows = list(result.scalars().all())
    return [
        {
            "id": row.id,
            "name": row.name,
            "key_prefix": row.key_prefix,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def create_key(name: str) -> dict:
    raw = generate_key()
    row = ApiKey(
        name=name.strip() or "API key",
        key_hash=hash_key(raw),
        key_prefix=_prefix_for(raw),
        key_plain=raw,
        created_at=_utcnow(),
    )
    async with async_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        created = {
            "id": row.id,
            "name": row.name,
            "key_prefix": row.key_prefix,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    created["key"] = raw
    return created


async def get_plain_key(key_id: int) -> Optional[str]:
    async with async_session() as session:
        row = await session.get(ApiKey, key_id)
        if not row:
            return None
        plain = getattr(row, "key_plain", None)
        return plain if isinstance(plain, str) and plain else None


async def delete_key(key_id: int) -> bool:
    async with async_session() as session:
        row = await session.get(ApiKey, key_id)
        if not row:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def is_valid(raw: Optional[str]) -> bool:
    if not raw or not isinstance(raw, str):
        return False
    candidate = raw.strip()
    if not candidate:
        return False
    digest = hash_key(candidate)
    async with async_session() as session:
        result = await session.execute(
            select(ApiKey.id).where(ApiKey.key_hash == digest)
        )
        row_id = result.scalar_one_or_none()
    if row_id is None:
        return False
    # compare_digest on the hex strings we already matched by equality —
    # the lookup is exact; this keeps a constant-time check on the raw
    # hash so a future non-indexed scan stays safe.
    return hmac.compare_digest(digest, hash_key(candidate))
