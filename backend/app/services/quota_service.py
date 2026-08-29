import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("qoderroute.quota")

QODER_BASE = "https://openapi.qoder.sh"

EXCHANGE_URL = f"{QODER_BASE}/api/v1/jobToken/exchange"
PLAN_URL = f"{QODER_BASE}/api/v2/user/plan"
QUOTA_URL = f"{QODER_BASE}/api/v2/quota/usage"

# Job-token cache: PAT -> (job_token, expires_at_epoch)
_job_token_cache: dict[str, tuple[str, float]] = {}
_job_token_locks: dict[str, asyncio.Lock] = {}


def _base_headers() -> dict[str, str]:
    from app.services import qoder_version
    version = qoder_version.get()
    return {
        "User-Agent": f"qoder/{version}",
        "Accept": "application/json",
        "X-Request-ID": str(uuid.uuid4()).upper(),
        "Cosy-Version": version,
        "Cosy-ClientType": "5",
        "Cosy-MachineOS": "x86_64_linux",
    }


async def _get_job_token(client: httpx.AsyncClient, pat: str) -> Optional[str]:
    """Exchange pt-* PAT for jt-* job token, cached until near expiry."""
    if not pat.startswith("pt-"):
        return pat

    cached = _job_token_cache.get(pat)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    lock = _job_token_locks.setdefault(pat, asyncio.Lock())
    async with lock:
        cached = _job_token_cache.get(pat)
        if cached and cached[1] > time.time() + 60:
            return cached[0]

        try:
            resp = await client.post(
                EXCHANGE_URL,
                headers={**_base_headers(), "Content-Type": "application/json"},
                json={"personal_token": pat},
            )
            if resp.status_code != 200:
                logger.warning(f"jobToken exchange HTTP {resp.status_code}")
                return None
            data = resp.json()
            token = data.get("token") or data.get("device_token") or data.get("access_token")
            expires_in = data.get("expires_in")
            if not isinstance(token, str) or not token:
                return None
            expires_epoch: Optional[float] = None
            expires_at = data.get("expires_at")
            if isinstance(expires_at, (int, float)):
                expires_epoch = float(expires_at)
                if expires_epoch > 10_000_000_000:  # milliseconds
                    expires_epoch /= 1000
            elif isinstance(expires_at, str) and expires_at.strip():
                try:
                    parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    expires_epoch = parsed.timestamp()
                except ValueError:
                    pass
            if expires_epoch is None:
                ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 23 * 3600
                # The exchange API currently reports 86400000 milliseconds;
                # treating it as seconds would retain a stale JT for years.
                if ttl > 7 * 24 * 3600:
                    ttl /= 1000
                expires_epoch = time.time() + ttl
            _job_token_cache[pat] = (token, expires_epoch)
            return token
        except Exception as e:
            logger.warning(f"jobToken exchange error: {e}")
            return None


def _parse_plan(plan: dict) -> dict:
    return {
        "plan_tier": str(plan.get("user_type") or ""),
        "plan_name": str(plan.get("plan_tier_name") or plan.get("plan_tier") or ""),
        "is_paid": bool(plan.get("is_paid_plan")),
        "end_date": plan.get("end_date"),
    }


def _parse_quota(quota: dict) -> dict:
    uq = quota.get("userQuota") if isinstance(quota.get("userQuota"), dict) else {}
    total = uq.get("total")
    used = uq.get("used")
    remaining = uq.get("remaining")
    percentage = uq.get("percentage", quota.get("totalUsagePercentage"))

    if remaining is None and isinstance(total, (int, float)):
        remaining = float(total) - (float(used) if isinstance(used, (int, float)) else 0.0)

    return {
        "quota_total": float(total) if isinstance(total, (int, float)) else None,
        "quota_used": float(used) if isinstance(used, (int, float)) else None,
        "quota_remaining": float(remaining) if isinstance(remaining, (int, float)) else None,
        "quota_percentage": float(percentage) if isinstance(percentage, (int, float)) else None,
        "is_quota_exceeded": bool(quota.get("isQuotaExceeded")),
        "quota_unit": str(uq.get("unit") or quota.get("usageType") or "credits"),
        "expires_at": quota.get("expiresAt"),
    }


async def fetch_plan_quota(pat: str) -> Optional[dict]:
    """Fetch plan + quota + userinfo for a PAT. Returns merged dict or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token = await _get_job_token(client, pat)
            if not token:
                return None

            headers = {**_base_headers(), "Authorization": f"Bearer {token}"}

            plan: dict = {}
            quota: dict = {}
            userinfo: dict = {}

            try:
                r = await client.get(PLAN_URL, headers=headers)
                if r.status_code == 200:
                    plan = r.json()
            except Exception as e:
                logger.warning(f"plan fetch error: {e}")

            try:
                r = await client.get(QUOTA_URL, headers=headers)
                if r.status_code == 200:
                    quota = r.json()
            except Exception as e:
                logger.warning(f"quota fetch error: {e}")

            try:
                r = await client.get(f"{QODER_BASE}/api/v1/userinfo", headers=headers)
                if r.status_code == 200:
                    userinfo = r.json()
            except Exception as e:
                logger.warning(f"userinfo fetch error: {e}")

            if not plan and not quota and not userinfo:
                return None

            result = {}
            if plan:
                result.update(_parse_plan(plan))
            if quota:
                result.update(_parse_quota(quota))
            result["plan_name"] = _plan_name_from_quota(
                str(result.get("plan_tier") or ""),
                str(result.get("plan_name") or ""),
                result.get("quota_total"),
            )
            if userinfo and userinfo.get("email"):
                result["email"] = str(userinfo["email"])
            account_name = display_name_from_userinfo(userinfo)
            if account_name:
                result["account_name"] = account_name
            result["quota_fetched_at"] = time.time()
            return result
    except Exception as e:
        logger.warning(f"fetch_plan_quota error: {e}")
        return None


def _first_str(obj: dict, keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str):
            stripped = val.strip()
            if stripped:
                return stripped
    return None


def display_name_from_userinfo(userinfo: Optional[dict]) -> Optional[str]:
    """Qoder profile name from /api/v1/userinfo — same keys as the CLI credential record."""
    if not isinstance(userinfo, dict):
        return None
    name = _first_str(userinfo, ("name", "username", "user_name"))
    return name[:128] if name else None


def resolve_account_name(explicit: Optional[str], plan_quota: Optional[dict] = None) -> str:
    """Prefer a caller-supplied label; otherwise the Qoder profile name, then email."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:128]
    if isinstance(plan_quota, dict):
        from_info = plan_quota.get("account_name")
        if isinstance(from_info, str) and from_info.strip():
            return from_info.strip()[:128]
        email = plan_quota.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip()[:128]
    return "account"


# Paid tiers are indistinguishable in the plan endpoint payload — the only
# reliable discriminator is the quota size. Map total credits to a display
# name (trials keep their own name from plan_tier_name; 300-credit trials
# are detected via the tier string, not the quota).
_PLAN_NAME_BY_QUOTA = (
    (20_000, "Ultra Plan"),
    (6_000, "Pro+ Plan"),
    (2_000, "Pro Plan"),
)


def _plan_name_from_quota(plan_tier: str, plan_name: str, quota_total) -> str:
    if "trial" in (plan_tier or "").lower():
        return plan_name  # trial name comes from the API already
    if isinstance(quota_total, (int, float)) and quota_total > 0:
        for threshold, name in _PLAN_NAME_BY_QUOTA:
            if quota_total >= threshold:
                return name
    return plan_name


async def get_job_token(pat: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=15) as client:
        return await _get_job_token(client, pat)


_uid_cache: dict[str, str] = {}


async def get_uid(pat: str) -> Optional[str]:
    if pat in _uid_cache:
        return _uid_cache[pat]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token = await _get_job_token(client, pat)
            if not token:
                return None
            r = await client.get(
                f"{QODER_BASE}/api/v1/userinfo",
                headers={**_base_headers(), "Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            uid = data.get("id") or data.get("user_id") or data.get("uid")
            if isinstance(uid, str) and uid:
                _uid_cache[pat] = uid
                return uid
    except Exception as e:
        logger.warning(f"get_uid error: {e}")
    return None


def looks_like_quota_error(message: str) -> bool:
    """Heuristic: does an upstream error message mean quota exhaustion?

    Deliberately excludes 429 / rate-limit markers — those are transient
    backpressure, not a spent plan. Treating them as quota exhaustion parks
    (or auto-deletes) a perfectly healthy account.
    """
    m = (message or "").lower()
    if any(
        k in m
        for k in (
            "quota",
            "credits exhausted",
            "credit_exhausted",
            "isquotaexceeded",
            "insufficient credits",
        )
    ):
        return True

    # Qoder's inference gateway also reports an exhausted/unentitled plan as
    # a 403 whose only payload is a redirect to its pricing page, e.g.
    # {"pricingUrl":"https://qoder.com/pricing?client=qoder"}.  There is no
    # literal "quota" marker in that response, but it has the same routing
    # semantics: park/delete this account and try the next one.
    return (
        "qoder.com/pricing?client=qoder" in m
        or (
            "403" in m
            and ("pricingurl" in m or "pricing_url" in m)
        )
    )


def looks_like_rate_limit(message: str) -> bool:
    """Heuristic: transient 429 / rate-limit backpressure (not quota)."""
    m = (message or "").lower()
    return "rate limit" in m or "rate_limit" in m or "ratelimit" in m or "429" in m


MODEL_QUEUE_ERROR_CODE = "10605"


def looks_like_model_queue(message: str) -> bool:
    """Heuristic: does an upstream error mean the model is queued (10605)?

    This is a transient server-side queue (isQueued), not an account failure —
    the account stays healthy and the client should retry.
    """
    return MODEL_QUEUE_ERROR_CODE in (message or "")


_TRANSIENT_STREAM_MARKERS = (
    "peer closed connection",
    "incomplete chunked read",
    "connection reset",
    "server disconnected",
    "connection aborted",
    "remote end closed connection",
)


def looks_like_transient_stream_error(message: str) -> bool:
    """Heuristic: a flaky mid-stream connection drop, safe to retry once."""
    m = (message or "").lower()
    return any(k in m for k in _TRANSIENT_STREAM_MARKERS)


def parse_model_queue(message: str) -> Optional[dict]:
    """Extract the 10605 queue payload from an upstream error message.

    The message looks like:
      upstream status 403: {"code":"10605","message":"{...isQueued...}"}
    Returns the inner dict (isQueued, retryAfterSeconds, ...) or None.
    """
    if not message or MODEL_QUEUE_ERROR_CODE not in message:
        return None
    try:
        start = message.index("{")
        outer = json.loads(message[start:])
    except (ValueError, json.JSONDecodeError):
        return None
    if str(outer.get("code")) != MODEL_QUEUE_ERROR_CODE:
        return None
    inner = outer.get("message")
    if isinstance(inner, dict):
        return inner
    if isinstance(inner, str):
        try:
            parsed = json.loads(inner)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, json.JSONDecodeError):
            return None
    return None
