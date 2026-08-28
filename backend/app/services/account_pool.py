import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

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
    ) -> Optional[Account]:
        """Fill-first routing: the first available account WITH quota wins.
        Requests stick to it until it exhausts/fails, then the next takes over."""
        await self._refresh_if_stale()

        now = _utcnow()
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
            # Un-park: quota came back, so the account rejoins routing right
            # away instead of waiting for the next pool refresh sweep.
            acc.is_available = True
            acc.cooldown_until = None
            acc.consecutive_failures = 0

            await session.commit()
            return data

    def _auto_delete_allowed_for(self, acc: Account) -> bool:
        """Return whether automatic deletion of exhausted accounts is enabled."""
        return bool(settings_service.get("accounts_auto_delete_exhausted"))

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
    ) -> None:
        """Persist counters and credit usage for a successful call."""
        try:
            async with async_session() as session:
                acc = await session.get(Account, account_id)
                if not acc:
                    return

                acc.last_used_at = _utcnow()
                acc.consecutive_failures = 0
                acc.last_error_message = None
                acc.is_available = not acc.is_quota_exceeded
                acc.cooldown_until = None

                # Counters via SQL expressions — concurrent completions on the
                # same account must not lose updates (fill-first routing makes
                # parallel calls on one account common).
                await session.execute(
                    update(Account)
                    .where(Account.id == account_id)
                    .values(
                        total_requests=func.coalesce(Account.total_requests, 0) + 1,
                        total_tokens=func.coalesce(Account.total_tokens, 0) + tokens_used,
                    )
                    .execution_options(synchronize_session=False)
                )
                session.expire(acc, ["total_requests", "total_tokens"])

                # Lifetime pool counter — survives account purges. Atomic
                # upsert for the same reason as the per-account counters:
                # read-modify-write loses credits under parallel completions,
                # and a plain INSERT races into IntegrityError.
                if credits_used:
                    await session.execute(
                        sqlite_insert(PoolCounter)
                        .values(key=CREDITS_SPENT_KEY, value=float(credits_used))
                        .on_conflict_do_update(
                            index_elements=[PoolCounter.key],
                            set_={"value": func.coalesce(PoolCounter.value, 0.0) + float(credits_used)},
                        )
                        .execution_options(synchronize_session=False)
                    )

                # Drain local quota estimate atomically — the ORM
                # read-modify-write used to lose decrements when fill-first
                # routing ran two completions on the same account. Expire the
                # columns afterwards so a later flush cannot overwrite the
                # SQL result with the stale in-memory values.
                drained = False
                if credits_used:
                    remaining_expr = Account.quota_remaining - float(credits_used)
                    result = await session.execute(
                        update(Account)
                        .where(
                            Account.id == account_id,
                            Account.quota_remaining.is_not(None),
                        )
                        .values(
                            quota_remaining=case(
                                (remaining_expr < 0, 0.0),
                                else_=remaining_expr,
                            ),
                            quota_used=func.coalesce(Account.quota_used, 0.0)
                            + float(credits_used),
                        )
                        .returning(Account.quota_remaining)
                        .execution_options(synchronize_session=False)
                    )
                    row = result.first()
                    drained = row is not None and row[0] is not None and row[0] <= 0
                    session.expire(acc, ["quota_remaining", "quota_used"])
                    if drained:
                        parked = await session.get(Account, account_id)
                        if parked:
                            await self._park_exhausted(
                                session, parked, "quota drained locally"
                            )
                            return

                await session.commit()
        except StaleDataError:
            # The account row was deleted (manual delete / auto-delete sweep)
            # while the request was in flight. The upstream completion itself
            # succeeded — nothing left to book.
            logger.warning(
                "mark_success: account %s deleted concurrently; skipping bookkeeping",
                account_id,
            )
            return

    async def mark_failure(self, account_id: int, error_message: str = ""):
        try:
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
                # An exhausted account stays parked — failures don't revive it.
                acc.is_available = is_available and not acc.is_quota_exceeded
                await session.commit()
        except StaleDataError:
            logger.warning(
                "mark_failure: account %s deleted concurrently; skipping",
                account_id,
            )

    async def list_accounts(self, session: AsyncSession) -> list[Account]:
        stmt = select(Account).order_by(Account.priority.desc(), Account.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_account_by_id(self, session: AsyncSession, account_id: int) -> Optional[Account]:
        return await session.get(Account, account_id)

    async def add_account(
        self, session: AsyncSession, name: str, pat_token: str,
        priority: int = 0, model_level: str = "auto", default_model: str = "",
    ) -> Account:
        existing = await session.execute(
            select(Account.id).where(Account.pat_token == pat_token)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("This PAT is already in the pool")

        account = Account(
            name=name,
            pat_token=pat_token,
            pat_short=pat_token[:12] + "..." if len(pat_token) > 15 else pat_token,
            priority=priority,
            model_level=model_level,
            default_model=default_model,
            # Generate unique machine_id for anti-fraud (random UUID per account)
            machine_id=str(uuid.uuid4()),
        )
        session.add(account)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise ValueError("This PAT is already in the pool")
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
            # Disable/enable was removed — is_active stays true via startup backfill.
            if key == "is_active":
                continue
            if value is not None and hasattr(acc, key):
                if key == "pat_token":
                    taken = await session.execute(
                        select(Account.id).where(
                            Account.pat_token == value,
                            Account.id != account_id,
                        )
                    )
                    if taken.scalar_one_or_none() is not None:
                        raise ValueError("This PAT is already in the pool")
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
