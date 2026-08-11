import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.account import Account
from app.models.pool_counter import PoolCounter, CREDITS_SPENT_KEY
from app.services import settings_service
from app.core.config import settings
from app.services import quota_service, logbus

logger = logging.getLogger("qoderroute.pool")


def _utcnow() -> datetime:
    """Naive UTC datetime — matches what SQLite stores/returns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _activity_decrement_statement(account_id: int, now_ms: float):
    return (
        update(Account)
        .where(
            Account.id == account_id,
            Account.activity_id == "qwen38_800_invoke",
            Account.activity_status == "active",
            Account.activity_remaining.is_not(None),
            Account.activity_remaining > 0,
            (
                Account.activity_expires_at.is_(None)
                | (Account.activity_expires_at > now_ms)
            ),
        )
        .values(
            activity_used=func.coalesce(Account.activity_used, 0) + 1,
            activity_remaining=Account.activity_remaining - 1,
            activity_status=case(
                (Account.activity_remaining <= 1, "exhausted"),
                else_="active",
            ),
        )
        .execution_options(synchronize_session=False)
    )


def _activity_priority_statement(
    now: datetime,
    now_ms: float,
    exclude_ids: Optional[set[int]] = None,
):
    """Exhausted credit accounts that can still spend a Qwen activity."""
    stmt = (
        select(Account)
        .where(
            Account.is_active == True,
            Account.is_quota_exceeded == True,
            Account.activity_id == "qwen38_800_invoke",
            Account.activity_status == "active",
            Account.activity_remaining.is_not(None),
            Account.activity_remaining > 0,
            (
                Account.activity_expires_at.is_(None)
                | (Account.activity_expires_at > now_ms)
            ),
            (
                Account.cooldown_until.is_(None)
                | (Account.cooldown_until < now)
            ),
            Account.consecutive_failures < settings.max_consecutive_failures,
        )
        .order_by(Account.priority.desc(), Account.id.asc())
    )
    if exclude_ids:
        stmt = stmt.where(Account.id.not_in(exclude_ids))
    return stmt


class AccountPool:
    _instance: Optional["AccountPool"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._last_refresh: datetime = datetime.min

    @classmethod
    async def get_instance(cls) -> "AccountPool":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._refresh()
        return cls._instance

    async def _refresh(self):
        """Recalculate is_available flags based on cooldown state.

        A served cooldown wipes the failure counter — the account gets a
        fresh chance instead of being parked forever at failures >= max.
        """
        async with async_session() as session:
            stmt = (
                select(Account)
                .where(Account.is_active == True)
                .order_by(Account.priority.desc(), Account.id.asc())
            )
            result = await session.execute(stmt)
            accounts = list(result.scalars().all())

            now = _utcnow()
            changed = False
            for acc in accounts:
                in_cooldown = acc.cooldown_until is not None and acc.cooldown_until > now
                if acc.cooldown_until is not None and not in_cooldown:
                    acc.cooldown_until = None
                    if acc.consecutive_failures:
                        acc.consecutive_failures = 0
                    changed = True
                should_be = not in_cooldown and not acc.is_quota_exceeded
                if acc.is_available != should_be:
                    acc.is_available = should_be
                    changed = True

            if changed:
                await session.commit()

            self._last_refresh = _utcnow()

    async def get_next_account(
        self,
        session: AsyncSession,
        exclude_ids: Optional[set[int]] = None,
        model_level: Optional[str] = None,
    ) -> Optional[Account]:
        """Fill-first routing: the first available account WITH quota wins.
        Requests stick to it until it exhausts/fails, then the next in line
        takes over. For Qwen3.8-Max, an exhausted credit account with an
        active free-call campaign is intentionally preferred first."""
        await self._refresh_if_stale()

        now = _utcnow()
        if model_level == "qmodel_38max":
            activity_result = await session.execute(
                _activity_priority_statement(now, time.time() * 1000, exclude_ids)
            )
            activity_account = activity_result.scalars().first()
            if activity_account is not None:
                return activity_account

        stmt = (
            select(Account)
            .where(Account.is_active == True, Account.is_available == True)
            .where(Account.is_quota_exceeded == False)
            .where(
                (Account.quota_remaining == None)
                | (Account.quota_remaining > 0)
            )
            .where(
                (Account.cooldown_until == None)
                | (Account.cooldown_until < now)
            )
            .where(Account.consecutive_failures < settings.max_consecutive_failures)
            .order_by(Account.priority.desc(), Account.id.asc())
        )
        result = await session.execute(stmt)
        available = list(result.scalars().all())

        if exclude_ids:
            available = [a for a in available if a.id not in exclude_ids]

        if not available:
            return None

        return available[0]

    async def refresh_quota(self, account_id: int) -> Optional[dict]:
        """Fetch live plan+quota from Qoder and persist on the account row."""
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return None

            data = await quota_service.fetch_plan_quota(acc.pat_token)
            if not data:
                return None

            if data.get("is_quota_exceeded"):
                await self._park_exhausted(session, acc, "quota refresh shows exhausted")
                return data

            mapping = {
                "plan_tier": "plan_tier",
                "plan_name": "plan_name",
                "is_paid": "is_paid",
                "end_date": "plan_end_date",
                "email": "email",
                "quota_total": "quota_total",
                "quota_used": "quota_used",
                "quota_remaining": "quota_remaining",
                "quota_percentage": "quota_percentage",
                "is_quota_exceeded": "is_quota_exceeded",
                "quota_unit": "quota_unit",
                "expires_at": "quota_expires_at",
                "quota_fetched_at": "quota_fetched_at",
            }
            for src, dst in mapping.items():
                if src in data and data[src] is not None:
                    setattr(acc, dst, data[src])

            # PAT proved healthy — drop the sticky error so the UI recovers.
            acc.last_error_message = None

            await session.commit()
            return data

    def _auto_delete_allowed_for(self, acc: Account) -> bool:
        """Auto-delete setting gates: main toggle on, keep-activity respected."""
        if not settings_service.get("accounts_auto_delete_exhausted"):
            return False
        if settings_service.get("accounts_auto_delete_keep_activity"):
            if acc.activity_status == "active" and (acc.activity_remaining or 0) > 0:
                return False
        return True

    async def delete_exhausted_accounts(self) -> int:
        """Bulk-delete every exhausted account (used when the setting turns on)."""
        async with async_session() as session:
            stmt = select(Account).where(Account.is_quota_exceeded == True)
            result = await session.execute(stmt)
            doomed = [a for a in result.scalars().all() if self._auto_delete_allowed_for(a)]
            for acc in doomed:
                logger.warning("Auto-deleting exhausted account %s (%d)", acc.name, acc.id)
                logbus.push(
                    "warn", "pool",
                    f"account auto-deleted (exhausted): {acc.name} (id {acc.id})",
                    account_id=acc.id, account_name=acc.name,
                )
                await session.delete(acc)
            await session.commit()
        if doomed:
            await self._refresh()
        return len(doomed)

    async def _park_exhausted(self, session: AsyncSession, acc: Account, reason: str):
        """Quota exhausted — keep the account in the pool but out of rotation.

        It stays visible ("quiet") and automatically rejoins routing if a
        later quota refresh shows credits again (mapping clears the flag).
        When auto-delete is enabled the account is removed instead of parked.
        """
        if self._auto_delete_allowed_for(acc):
            logger.warning(
                "Account %s (%d) exhausted (%s); auto-deleting",
                acc.name, acc.id, reason,
            )
            logbus.push("warn", "pool", f"account auto-deleted (exhausted): {acc.name} (id {acc.id})", account_id=acc.id, account_name=acc.name, reason=reason)
            await session.delete(acc)
            await session.commit()
            return
        logger.warning(
            "Account %s (%d) exhausted (%s); parking",
            acc.name, acc.id, reason,
        )
        logbus.push("warn", "pool", f"account parked (exhausted): {acc.name} (id {acc.id})", account_id=acc.id, account_name=acc.name, reason=reason)
        acc.is_quota_exceeded = True
        acc.is_available = False
        acc.quota_remaining = 0.0
        await session.commit()

    async def mark_quota_exceeded(self, account_id: int):
        """Quota-exceeded signal from the API — park the account (kept, unused)."""
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return
            await self._park_exhausted(session, acc, "api reported quota exceeded")

    async def refresh_all_quotas(self) -> int:
        """Refresh plan/quota for every active, non-exhausted account.

        Exhausted accounts are left alone — the backend never polls Qoder for
        them. They only rejoin when the user manually refreshes the account
        (refresh_quota) and it comes back with credits.
        """
        async with async_session() as session:
            stmt = select(Account).where(
                Account.is_active == True,
                Account.is_quota_exceeded == False,
            )
            result = await session.execute(stmt)
            ids = [a.id for a in result.scalars().all()]

        ok = 0
        for account_id in ids:
            data = await self.refresh_quota(account_id)
            if data:
                ok += 1
            await asyncio.sleep(0.3)  # be polite to the API
        return ok

    async def mark_success(
        self,
        account_id: int,
        tokens_used: int = 0,
        credits_used: float = 0.0,
        model_level: Optional[str] = None,
    ) -> bool:
        """Persist a successful call; return whether a free activity slot paid."""
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return False

            acc.last_used_at = _utcnow()
            acc.consecutive_failures = 0
            acc.last_error_message = None
            # A successful free activity call does not replenish the regular
            # credit quota. Keep exhausted accounts out of other models.
            acc.is_available = not acc.is_quota_exceeded
            acc.cooldown_until = None
            acc.total_requests = (acc.total_requests or 0) + 1
            acc.total_tokens = (acc.total_tokens or 0) + tokens_used

            # One successful upstream completion is one campaign invocation.
            # Keep this atomic so concurrent tool-loop turns cannot overwrite
            # each other's local estimate.
            activity_consumed = False
            if model_level == "qmodel_38max":
                now_ms = time.time() * 1000
                await session.flush()
                activity_result = await session.execute(
                    _activity_decrement_statement(account_id, now_ms)
                )
                activity_consumed = getattr(activity_result, "rowcount", 0) > 0

            billable_credits = 0.0 if activity_consumed else credits_used
            if activity_consumed and credits_used:
                logger.warning(
                    "Upstream reported %.6f credits for activity call on account %s; "
                    "suppressing local charge",
                    credits_used,
                    account_id,
                )
                logbus.push(
                    "warn",
                    "activity",
                    "upstream reported credits for free activity call; local charge suppressed",
                    account_id=account_id,
                    upstream_credits=credits_used,
                )

            # Lifetime pool counter — survives account purges.
            if billable_credits:
                counter = await session.get(PoolCounter, CREDITS_SPENT_KEY)
                if counter is None:
                    counter = PoolCounter(key=CREDITS_SPENT_KEY, value=0.0)
                    session.add(counter)
                counter.value += billable_credits

            # Drain local quota estimate; keep used+remaining in sync so the bar matches.
            if billable_credits and acc.quota_remaining is not None:
                acc.quota_remaining = max(0.0, acc.quota_remaining - billable_credits)
                if acc.quota_used is not None:
                    acc.quota_used = acc.quota_used + billable_credits
                if acc.quota_remaining <= 0:
                    await self._park_exhausted(session, acc, "quota drained locally")
                    return activity_consumed

            await session.commit()
            return activity_consumed

    async def mark_failure(self, account_id: int, error_message: str = ""):
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return

            new_failures = acc.consecutive_failures + 1
            cooldown_until = None
            is_available = True

            if new_failures >= settings.max_consecutive_failures:
                backoff = 2 ** (new_failures - settings.max_consecutive_failures + 1)
                cooldown_until = _utcnow() + timedelta(
                    seconds=settings.account_cooldown_seconds * backoff
                )
                is_available = False
                logger.warning(
                    "Account %s cooldown until %s (%d failures)",
                    acc.name, cooldown_until, new_failures,
                )

            acc.consecutive_failures = new_failures
            acc.last_error_at = _utcnow()
            acc.last_error_message = error_message[:512]
            acc.cooldown_until = cooldown_until
            acc.is_available = is_available
            await session.commit()

    async def list_accounts(self, session: AsyncSession) -> list[Account]:
        stmt = select(Account).order_by(Account.priority.desc(), Account.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_account_by_id(self, session: AsyncSession, account_id: int) -> Optional[Account]:
        return await session.get(Account, account_id)

    async def add_account(
        self, session: AsyncSession, name: str, pat_token: str,
        priority: int = 0, model_level: str = "auto",
    ) -> Account:
        account = Account(
            name=name,
            pat_token=pat_token,
            pat_short=pat_token[:12] + "..." if len(pat_token) > 15 else pat_token,
            priority=priority,
            model_level=model_level,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        await self._refresh()
        logbus.push("info", "pool", f"account added: {name} (id {account.id})", account_id=account.id, account_name=name)
        return account

    async def remove_account(self, session: AsyncSession, account_id: int) -> bool:
        acc = await session.get(Account, account_id)
        if not acc:
            return False
        await session.delete(acc)
        await session.commit()
        await self._refresh()
        return True

    async def update_account(self, session: AsyncSession, account_id: int, **kwargs) -> Optional[Account]:
        acc = await session.get(Account, account_id)
        if not acc:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(acc, key):
                if key == "pat_token":
                    acc.pat_short = value[:12] + "..."
                setattr(acc, key, value)
        await session.commit()
        await session.refresh(acc)
        await self._refresh()
        return acc

    async def get_stats(self, session: AsyncSession) -> dict:
        stmt = select(
            func.count(Account.id).label("total"),
            func.sum(Account.total_requests).label("total_req"),
            func.sum(Account.total_tokens).label("total_tok"),
        )
        result = await session.execute(stmt)
        row = result.one()

        active_stmt = select(func.count(Account.id)).where(Account.is_active == True)
        active_count = (await session.execute(active_stmt)).scalar() or 0

        avail_stmt = select(func.count(Account.id)).where(
            Account.is_active == True, Account.is_available == True
        )
        available_now = (await session.execute(avail_stmt)).scalar() or 0

        now = _utcnow()
        cd_stmt = select(func.count(Account.id)).where(
            Account.is_active == True,
            Account.cooldown_until != None,
            Account.cooldown_until > now,
        )
        in_cooldown = (await session.execute(cd_stmt)).scalar() or 0

        spent_stmt = select(PoolCounter.value).where(PoolCounter.key == CREDITS_SPENT_KEY)
        credits_spent = (await session.execute(spent_stmt)).scalar() or 0.0

        return {
            "total_accounts": row.total or 0,
            "active_accounts": active_count,
            "available_now": available_now,
            "accounts_in_cooldown": in_cooldown,
            "total_requests": row.total_req or 0,
            "total_tokens": row.total_tok or 0,
            "credits_spent": credits_spent,
        }

    async def _refresh_if_stale(self):
        now = _utcnow()
        if (now - self._last_refresh).total_seconds() > settings.qoder_poll_interval:
            await self._refresh()


pool = AccountPool()
