import json

import pytest

from app.api.models import list_models, model_catalog
from app.services import direct_client, model_probe, settings_service
from app.services.model_catalog import (
    DEFAULT_PROBE_MODEL_KEYS,
    MODEL_CATALOG,
    MODEL_KEYS_IN_ORDER,
)


def test_catalog_has_all_unique_models_and_known_credit_factors() -> None:
    assert len(MODEL_CATALOG) == 15
    assert len(set(MODEL_KEYS_IN_ORDER)) == len(MODEL_CATALOG)
    by_key = {entry["key"]: entry for entry in MODEL_CATALOG}
    assert by_key["cmodel"]["name"] == "Cantus"
    assert by_key["cmodel"]["credit_factor"] == 3.2
    assert by_key["qmodel_38max"]["credit_factor"] == 0.5
    assert by_key["lite"]["credit_factor"] == 0.0


@pytest.mark.parametrize("entry", MODEL_CATALOG)
def test_every_catalog_model_is_routable_with_native_identity(entry: dict) -> None:
    key = entry["key"]
    assert direct_client.MODEL_KEY_MAP[key] == key
    body = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": "hello"}],
            model_key=key,
            tools=None,
        )
    )
    assert body["model_config"]["key"] == key
    assert body["model_config"]["display_name"] == entry["name"]
    assert body["model_config"]["is_reasoning"] is entry["is_reasoning"]


@pytest.mark.asyncio
async def test_catalog_api_and_openai_models_share_credit_metadata() -> None:
    catalog = await model_catalog()
    openai = await list_models()

    assert [row["key"] for row in catalog] == list(MODEL_KEYS_IN_ORDER)
    assert [row["id"] for row in openai["data"]] == list(MODEL_KEYS_IN_ORDER)
    assert openai["data"][5]["credit_factor"] == 3.2
    by_key = {row["key"]: row for row in catalog}
    assert by_key["kmodel_latest"]["is_reasoning"] is False
    assert by_key["kmodel_latest"]["supports_thinking"] is True
    assert by_key["kmodel_latest"]["thinking_efforts"] == ["low", "high", "max"]
    assert by_key["kmodel_latest"]["default_thinking_effort"] == "max"
    assert by_key["kmodel"]["is_reasoning"] is False
    assert by_key["kmodel"]["supports_thinking"] is False


def test_probe_selection_is_runtime_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = dict(settings_service._DEFAULTS)
    monkeypatch.setattr(settings_service, "_cache", cache)

    assert [key for _, key in model_probe._probe_models()] == list(
        DEFAULT_PROBE_MODEL_KEYS
    )

    cache["probe_model_keys"] = ["ultimate", "cmodel"]
    assert model_probe._probe_models() == [
        ("Ultimate", "ultimate"),
        ("Cantus", "cmodel"),
    ]

    cache["probe_model_keys"] = []
    assert model_probe._probe_models() == []
