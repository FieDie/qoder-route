"""Qoder account activities: discovery, claim, signed balance and estimates."""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.database import async_session
from app.models.account import Account
from app.services import logbus, quota_service, settings_service, signer_service
from app.services.direct_client import (
    QODER_INFER_USER_AGENT,
    _resolve_infer_base,
    _traceparent,
)

logger = logging.getLogger("qoderroute.activity")

TARGET_ACTIVITY_ID = "qwen38_800_invoke"
TARGET_MODEL = "qmodel_38max"
DEFAULT_LIMIT = 800
OPENAPI_BASE = "https://openapi.qoder.sh"
ELIGIBILITY_URL = f"{OPENAPI_BASE}/api/v2/activity/claim/eligibility"
CLAIM_URL = f"{OPENAPI_BASE}/api/v2/activity/claim"


def checks_enabled() -> bool:
    return bool(settings_service.get("account_activity_checks_enabled"))


def _activity_headers(token: str, machine_token: Optional[str] = None) -> dict[str, str]:
    headers = {
        **quota_service._base_headers(),
        "Authorization": f"Bearer {token}",
        "Accept-Language": "en-US",
    }
    if machine_token:
        headers["Cosy-MachineToken"] = machine_token
    return headers


def _label(item: dict[str, Any]) -> str:
    text = item.get("cliText")
    if isinstance(text, str) and text.strip():
        return text.strip()
    claim_text = item.get("claimText")
    if isinstance(claim_text, dict):
        for key in ("en", "zh"):
            value = claim_text.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "800 free Qwen3.8-Max requests"


def _matching_activity(payload: Any) -> Optional[dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    return next(
        (
            item for item in rows
            if isinstance(item, dict) and item.get("activityId") == TARGET_ACTIVITY_ID
        ),
        None,
    )


def _matching_balance(payload: Any) -> Optional[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("activities") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    return next(
        (
            item for item in rows
            if isinstance(item, dict) and item.get("activityId") == TARGET_ACTIVITY_ID
        ),
        None,
    )


async def _eligibility(account: Account) -> Optional[dict[str, Any]]:
    token = await quota_service.get_job_token(account.pat_token)
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                ELIGIBILITY_URL,
                headers=_activity_headers(token, account.machine_token),
            )
        if response.status_code != 200:
            logger.warning("Activity eligibility HTTP %s for account %s", response.status_code, account.id)
            return None
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            return None
        # Empty object means the request succeeded but this campaign is not
        # available; ``None`` is reserved for transport/parser failures so a
        # transient outage does not erase a previously active card.
        return _matching_activity(payload) or {}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Activity eligibility failed for account %s: %s", account.id, exc)
        return None


async def _signed_balance(account: Account) -> Optional[dict[str, Any]]:
    if not account.machine_id or not account.machine_token:
        return None
    token = await quota_service.get_job_token(account.pat_token)
    uid = await quota_service.get_uid(account.pat_token)
    if not token or not uid:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as signer_client:
            signed_response = await signer_service.post_to_signer(
                "/activity",
                client=signer_client,
                json={
                    "jt": token,
                    "uid": uid,
                    "machine_id": account.machine_id,
                    "machine_token": account.machine_token,
                    "base_url": _resolve_infer_base(),
                },
            )
            if signed_response.status_code != 200:
                return None
            signed = signed_response.json()
        if not isinstance(signed, dict):
            return None
        url, headers, body_b64 = signed.get("url"), signed.get("headers"), signed.get("body_b64")
        allowed_urls = {
            f"https://api{i}.qoder.sh/algo/api/v2/activity" for i in (1, 2, 3)
        }
        if url not in allowed_urls or not isinstance(headers, dict) or not isinstance(body_b64, str):
            return None
        headers.setdefault("Cosy-Version", "1.1.17")
        headers.setdefault("Cosy-ClientType", "5")
        headers.setdefault("Cosy-MachineOS", "x86_64_linux")
        headers.setdefault("User-Agent", QODER_INFER_USER_AGENT)
        headers.setdefault("traceparent", _traceparent())
        request_body = base64.b64decode(body_b64, validate=True)
        async with httpx.AsyncClient(timeout=30) as upstream:
            response = await upstream.request(
                "GET",
                url,
                headers=headers,
                content=request_body or None,
            )
        if response.status_code != 200:
            logger.warning("Activity balance HTTP %s for account %s", response.status_code, account.id)
            return None
        try:
            payload = response.json()
        except ValueError:
            async with httpx.AsyncClient(timeout=20) as signer_client:
                decrypted = await signer_service.post_to_signer(
                    "/decrypt",
                    client=signer_client,
                    json={"payload": response.text},
                )
            plain = decrypted.json().get("plain") if decrypted.status_code == 200 else None
            payload = json.loads(plain) if isinstance(plain, str) else None
        return _matching_balance(payload)
    except (httpx.HTTPError, OSError, ValueError, TypeError, signer_service.SignerUnavailableError) as exc:
        logger.warning("Activity balance failed for account %s: %s", account.id, exc)
        return None


def _clear_activity(account: Account, checked_at: float) -> None:
    account.activity_id = None
    account.activity_status = None
    account.activity_label = None
    account.activity_model = None
    account.activity_limit = None
    account.activity_used = 0
    account.activity_remaining = None
    account.activity_expires_at = None
    account.activity_claimed_at = None
    account.activity_checked_at = checked_at


async def refresh_account_activity(account_id: int, *, force: bool = False) -> Optional[Account]:
    """Refresh one account. Failures are local diagnostics, never pool failures."""
    if not force and not checks_enabled():
        return None
    async with async_session() as session:
        account = await session.get(Account, account_id)
        if account is None:
            return None
        item = await _eligibility(account)
        if item is None:
            # A network/parser failure is indistinguishable from no payload;
            # retain prior state instead of making an active campaign vanish.
            return account

        now = time.time()
        claimed = bool(item.get("claimed")) or str(item.get("reason") or "").upper() == "ALREADY_CLAIMED"
        claimable = bool(item.get("canClaim")) and not claimed
        if not claimed and not claimable:
            _clear_activity(account, now)
            await session.commit()
            return account

        account.activity_id = TARGET_ACTIVITY_ID
        account.activity_status = "active" if claimed else "claimable"
        account.activity_label = _label(item)
        account.activity_model = TARGET_MODEL
        account.activity_limit = account.activity_limit or DEFAULT_LIMIT
        account.activity_used = account.activity_used or 0
        account.activity_remaining = (
            account.activity_remaining
            if account.activity_remaining is not None
            else max(0, account.activity_limit - account.activity_used)
        )
        end_at = item.get("activityEndAt")
        if isinstance(end_at, (int, float)):
            account.activity_expires_at = float(end_at)
        account.activity_checked_at = now

        if claimed:
            balance = await _signed_balance(account)
            if balance:
                limit = balance.get("limit")
                remaining = balance.get("remaining")
                if isinstance(limit, (int, float)):
                    account.activity_limit = max(0, int(limit))
                if isinstance(remaining, (int, float)):
                    account.activity_remaining = max(0, int(remaining))
                    account.activity_used = max(0, (account.activity_limit or DEFAULT_LIMIT) - account.activity_remaining)
                    if account.activity_remaining <= 0:
                        account.activity_status = "exhausted"
                balance_end = balance.get("activityEndAt")
                if isinstance(balance_end, (int, float)):
                    account.activity_expires_at = float(balance_end)
        if account.activity_expires_at is not None and account.activity_expires_at <= now * 1000:
            account.activity_status = "exhausted"
        await session.commit()
        await session.refresh(account)
        return account


async def claim_account_activity(account_id: int) -> Account:
    async with async_session() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise LookupError("Account not found")
        if account.activity_id != TARGET_ACTIVITY_ID or account.activity_status != "claimable":
            raise ValueError("Activity is not claimable")
        token = await quota_service.get_job_token(account.pat_token)
        if not token:
            raise RuntimeError("Job token exchange failed")
        url = f"{CLAIM_URL}?activityId={quote(TARGET_ACTIVITY_ID, safe='')}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                headers=_activity_headers(token, account.machine_token),
                content=b"",
            )
        if response.status_code != 200:
            raise RuntimeError(f"Qoder claim HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Qoder claim returned invalid JSON") from exc
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            message = payload.get("message") if isinstance(payload, dict) else None
            raise RuntimeError(f"Qoder rejected claim{f': {message}' if message else ''}")

        now = time.time()
        account.activity_status = "active"
        account.activity_limit = DEFAULT_LIMIT
        account.activity_used = 0
        account.activity_remaining = DEFAULT_LIMIT
        account.activity_claimed_at = now
        account.activity_checked_at = now
        await session.commit()
        await session.refresh(account)
        logbus.push(
            "info", "activity", "activity claimed",
            account_id=account.id, activity_id=TARGET_ACTIVITY_ID, limit=DEFAULT_LIMIT,
        )
        return account


async def attach_machine_identity_from_attempt(
    account_id: int,
    *,
    attempt_path: Optional[str] = None,
    email: Optional[str] = None,
) -> bool:
    """Attach the worker's machine identity without exposing it through API."""
    root = Path(settings.worker_script).resolve().parent
    candidates: list[Path] = []
    if attempt_path:
        candidate = Path(attempt_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root / "attempts" / "successfully")
            candidates.append(candidate)
        except (OSError, ValueError):
            pass
    if not candidates and email:
        folder = root / "attempts" / "successfully"
        try:
            candidates = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            candidates = []

    for candidate in candidates[:200]:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        account_info = payload.get("account") if isinstance(payload, dict) else None
        attempt_email = account_info.get("email") if isinstance(account_info, dict) else None
        # An account with a known email only accepts attempt files carrying
        # that SAME email. A file without an email is not a wildcard — it
        # would attach a random machine identity to this account.
        if email and str(attempt_email or "").casefold() != email.casefold():
            continue
        machine_id = payload.get("machine_id") if isinstance(payload, dict) else None
        machine_token = payload.get("machine_token") if isinstance(payload, dict) else None
        if not isinstance(machine_id, str) or not isinstance(machine_token, str):
            continue
        async with async_session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                return False
            account.machine_id = machine_id
            account.machine_token = machine_token
            machine_type = payload.get("machine_type")
            account.machine_type = str(machine_type) if machine_type is not None else None
            await session.commit()
        return True
    return False
