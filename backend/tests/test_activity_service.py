from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.account import Account
from app.models.pool_counter import PoolCounter
from app.services import account_pool, activity_service


class _FakeAsyncSession:
    def __init__(self, account: Account, activity_rowcount: int = 0) -> None:
        self.account = account
        self.activity_rowcount = activity_rowcount
        self.committed = False
        self.added: list[object] = []

    async def get(self, model, key):
        if model is Account and key == self.account.id:
            return self.account
        return None

    async def flush(self) -> None:
        return None

    async def execute(self, statement):
        return SimpleNamespace(rowcount=self.activity_rowcount)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, value) -> None:
        return None


class _FakeSessionContext:
    def __init__(self, session: _FakeAsyncSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _account(**values) -> Account:
    defaults = {
        "id": 7,
        "name": "activity-test",
        "pat_token": "pt-test",
        "pat_short": "pt-test",
        "activity_used": 0,
    }
    defaults.update(values)
    return Account(**defaults)


@pytest.mark.asyncio
async def test_refresh_exposes_claimable_target(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account()
    session = _FakeAsyncSession(account)
    monkeypatch.setattr(activity_service, "async_session", lambda: _FakeSessionContext(session))

    async def fake_eligibility(value):
        return {
            "activityId": activity_service.TARGET_ACTIVITY_ID,
            "canClaim": True,
            "claimed": False,
            "cliText": "800 Qwen3.8-Max free calls",
            "activityEndAt": 1_900_000_000_000,
        }

    monkeypatch.setattr(activity_service, "_eligibility", fake_eligibility)
    refreshed = await activity_service.refresh_account_activity(account.id, force=True)

    assert refreshed is account
    assert session.committed is True
    assert account.activity_status == "claimable"
    assert account.activity_model == "qmodel_38max"
    assert account.activity_limit == 800
    assert account.activity_remaining == 800
    assert account.activity_label == "800 Qwen3.8-Max free calls"


@pytest.mark.asyncio
async def test_claimed_activity_uses_signed_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(machine_id="machine-id", machine_token="machine-token")
    session = _FakeAsyncSession(account)
    monkeypatch.setattr(activity_service, "async_session", lambda: _FakeSessionContext(session))

    async def fake_eligibility(value):
        return {
            "activityId": activity_service.TARGET_ACTIVITY_ID,
            "canClaim": False,
            "claimed": True,
            "reason": "ALREADY_CLAIMED",
        }

    async def fake_balance(value):
        return {"activityId": activity_service.TARGET_ACTIVITY_ID, "limit": 800, "remaining": 731}

    monkeypatch.setattr(activity_service, "_eligibility", fake_eligibility)
    monkeypatch.setattr(activity_service, "_signed_balance", fake_balance)
    refreshed = await activity_service.refresh_account_activity(account.id, force=True)

    assert refreshed is account
    assert account.activity_status == "active"
    assert account.activity_used == 69
    assert account.activity_remaining == 731


@pytest.mark.asyncio
async def test_successful_check_without_campaign_hides_stale_card(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(
        activity_id=activity_service.TARGET_ACTIVITY_ID,
        activity_status="active",
        activity_limit=800,
        activity_remaining=700,
    )
    session = _FakeAsyncSession(account)
    monkeypatch.setattr(activity_service, "async_session", lambda: _FakeSessionContext(session))

    async def no_campaign(value):
        return {}

    monkeypatch.setattr(activity_service, "_eligibility", no_campaign)
    await activity_service.refresh_account_activity(account.id, force=True)

    assert account.activity_id is None
    assert account.activity_status is None
    assert account.activity_remaining is None


def test_qwen_decrement_is_atomic_and_stops_at_zero() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = _account(
            activity_id=activity_service.TARGET_ACTIVITY_ID,
            activity_status="active",
            activity_model="qmodel_38max",
            activity_limit=800,
            activity_used=798,
            activity_remaining=2,
        )
        session.add(account)
        session.commit()
        for _ in range(3):
            session.execute(account_pool._activity_decrement_statement(account.id, 0))
            session.commit()
        result = session.scalar(select(Account).where(Account.id == account.id))

    assert result is not None
    assert result.activity_used == 800
    assert result.activity_remaining == 0
    assert result.activity_status == "exhausted"


def test_exhausted_activity_account_is_selected_before_credit_pool() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        free_activity = _account(
            id=1,
            name="free-activity",
            is_active=True,
            is_available=False,
            is_quota_exceeded=True,
            consecutive_failures=0,
            priority=0,
            activity_id=activity_service.TARGET_ACTIVITY_ID,
            activity_status="active",
            activity_limit=800,
            activity_used=100,
            activity_remaining=700,
        )
        live_credits = _account(
            id=2,
            name="live-credits",
            is_active=True,
            is_available=True,
            is_quota_exceeded=False,
            consecutive_failures=0,
            priority=100,
            quota_remaining=500,
        )
        session.add_all([free_activity, live_credits])
        session.commit()

        selected = session.scalars(
            account_pool._activity_priority_statement(account_pool._utcnow(), 0)
        ).first()
        excluded = session.scalars(
            account_pool._activity_priority_statement(account_pool._utcnow(), 0, {1})
        ).first()

    assert selected is not None and selected.id == 1
    assert excluded is None


def test_expired_or_depleted_activity_is_not_selected() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            _account(
                id=1,
                is_active=True,
                is_quota_exceeded=True,
                consecutive_failures=0,
                activity_id=activity_service.TARGET_ACTIVITY_ID,
                activity_status="active",
                activity_remaining=5,
                activity_expires_at=100,
            ),
            _account(
                id=2,
                is_active=True,
                is_quota_exceeded=True,
                consecutive_failures=0,
                activity_id=activity_service.TARGET_ACTIVITY_ID,
                activity_status="exhausted",
                activity_remaining=0,
            ),
        ])
        session.commit()
        selected = session.scalars(
            account_pool._activity_priority_statement(account_pool._utcnow(), 101)
        ).first()

    assert selected is None


@pytest.mark.asyncio
async def test_consumed_activity_slot_suppresses_local_credit_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(
        is_quota_exceeded=False,
        quota_remaining=100.0,
        quota_used=20.0,
    )
    session = _FakeAsyncSession(account, activity_rowcount=1)
    monkeypatch.setattr(account_pool, "async_session", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(account_pool.logbus, "push", lambda *args, **kwargs: None)

    consumed = await account_pool.pool.mark_success(
        account.id,
        tokens_used=10,
        credits_used=5.0,
        model_level="qmodel_38max",
    )

    assert consumed is True
    assert account.quota_remaining == 100.0
    assert account.quota_used == 20.0
    assert not any(isinstance(value, PoolCounter) for value in session.added)


@pytest.mark.asyncio
async def test_credit_charge_resumes_when_no_activity_slot_was_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(
        is_quota_exceeded=False,
        quota_remaining=100.0,
        quota_used=20.0,
    )
    session = _FakeAsyncSession(account, activity_rowcount=0)
    monkeypatch.setattr(account_pool, "async_session", lambda: _FakeSessionContext(session))

    consumed = await account_pool.pool.mark_success(
        account.id,
        tokens_used=10,
        credits_used=5.0,
        model_level="qmodel_38max",
    )

    assert consumed is False
    assert account.quota_remaining == 95.0
    assert account.quota_used == 25.0
    counters = [value for value in session.added if isinstance(value, PoolCounter)]
    assert len(counters) == 1 and counters[0].value == 5.0


def test_signer_activity_route_is_hardcoded_and_not_generic() -> None:
    source = (Path(__file__).resolve().parents[1] / "signer" / "signer_server.mjs").read_text(encoding="utf-8")
    assert 'req.url === "/activity"' in source
    assert '"/algo/api/v2/activity"' in source
    assert '"GET"' in source
    assert "allowedBases" in source
    assert "input.request_path" not in source
