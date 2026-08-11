from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.settings import SettingsUpdate
from app.services import direct_client, settings_service


class _FakeSession:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.added: list[object] = []
        self.committed = False

    async def get(self, model, key: str):
        return self.rows.get(key)

    def add(self, row: object) -> None:
        self.rows[getattr(row, "key")] = row
        self.added.append(row)

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def test_settings_contract_accepts_only_known_qoder_infer_bases() -> None:
    for value in ("api1", "api2", "api3"):
        assert SettingsUpdate(qoder_infer_base=value).qoder_infer_base == value

    with pytest.raises(ValidationError):
        SettingsUpdate(qoder_infer_base="api4")


def test_activity_checks_setting_defaults_on_and_accepts_boolean() -> None:
    assert settings_service._DEFAULTS["account_activity_checks_enabled"] is True
    assert SettingsUpdate(account_activity_checks_enabled=False).account_activity_checks_enabled is False


def test_infer_route_switch_is_read_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_cache = dict(settings_service._DEFAULTS)
    monkeypatch.setattr(settings_service, "_cache", runtime_cache)
    monkeypatch.setattr(direct_client, "INFER_BASE", "")

    runtime_cache["qoder_infer_base"] = "api1"
    assert direct_client._resolve_infer_base() == "https://api1.qoder.sh"

    runtime_cache["qoder_infer_base"] = "api2"
    assert direct_client._resolve_infer_base() == "https://api2.qoder.sh"


@pytest.mark.asyncio
async def test_qoder_infer_base_is_persisted_and_visible_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    monkeypatch.setattr(
        settings_service,
        "_cache",
        dict(settings_service._DEFAULTS),
    )
    monkeypatch.setattr(
        settings_service,
        "async_session",
        lambda: _FakeSessionContext(session),
    )

    snapshot = await settings_service.update({"qoder_infer_base": "api1"})

    assert session.committed is True
    assert len(session.added) == 1
    assert getattr(session.added[0], "key") == "qoder_infer_base"
    assert getattr(session.added[0], "value") == "api1"
    assert snapshot["qoder_infer_base"] == "api1"
    assert settings_service.get_qoder_infer_base() == "api1"


@pytest.mark.asyncio
async def test_invalid_persisted_qoder_infer_base_falls_back_to_api3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [SimpleNamespace(key="qoder_infer_base", value="api9")]
        )
    )

    class _LoadSession(_FakeSession):
        async def execute(self, statement):
            return result

    session = _LoadSession()
    monkeypatch.setattr(settings_service, "_cache", {"qoder_infer_base": "api1"})
    monkeypatch.setattr(
        settings_service,
        "async_session",
        lambda: _FakeSessionContext(session),
    )

    await settings_service.load()

    assert settings_service.get_qoder_infer_base() == "api3"
    assert settings_service.snapshot()["qoder_infer_base"] == "api3"
