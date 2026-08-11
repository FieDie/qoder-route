from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.api import chat
from app.models.schemas import ChatCompletionRequest
from app.services import direct_client, signer_service


SIGNER_ERROR = "signer unavailable: All connection attempts failed"


@pytest.mark.asyncio
async def test_concurrent_ensure_starts_only_one_signer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"healthy": False, "spawns": 0}

    async def fake_health(timeout: float = 1.0) -> bool:
        await asyncio.sleep(0)
        return state["healthy"]

    class FakeProcess:
        pid = 12345

        @staticmethod
        def poll():
            return None

    def fake_spawn():
        state["spawns"] += 1
        state["healthy"] = True
        return FakeProcess()

    async def fake_process_lock(timeout: float):
        return object()

    monkeypatch.setattr(signer_service, "signer_is_healthy", fake_health)
    monkeypatch.setattr(signer_service, "_spawn_signer", fake_spawn)
    monkeypatch.setattr(
        signer_service,
        "_retire_unhealthy_owned_process",
        AsyncMock(),
    )
    monkeypatch.setattr(signer_service, "_acquire_process_lock", fake_process_lock)
    monkeypatch.setattr(signer_service, "_release_process_lock", lambda handle: None)
    monkeypatch.setattr(signer_service, "_ensure_lock", asyncio.Lock())

    results = await asyncio.gather(
        signer_service.ensure_signer(),
        signer_service.ensure_signer(),
        signer_service.ensure_signer(),
    )

    assert results == [True, True, True]
    assert state["spawns"] == 1


@pytest.mark.asyncio
async def test_signer_transport_failure_recovers_and_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", f"{signer_service.SIGNER_URL}/infer")
    expected = httpx.Response(200, json={"ok": True}, request=request)
    client = SimpleNamespace(
        post=AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused", request=request),
                expected,
            ]
        )
    )
    ensure = AsyncMock(return_value=True)
    monkeypatch.setattr(signer_service, "ensure_signer", ensure)

    response = await signer_service.post_to_signer(
        "/infer",
        json={"request": "body"},
        client=client,
    )

    assert response is expected
    ensure.assert_awaited_once()
    assert client.post.await_count == 2


@pytest.mark.asyncio
async def test_malformed_signer_response_becomes_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(direct_client, "get_job_token", AsyncMock(return_value="jt"))
    monkeypatch.setattr(direct_client, "get_uid", AsyncMock(return_value="uid"))
    monkeypatch.setattr(direct_client, "_get_signer", lambda: client)
    try:
        events = [
            event
            async for event in direct_client.run_infer(
                "pat",
                "kmodel_latest",
                [{"role": "user", "content": "hello"}],
            )
        ]
    finally:
        await client.aclose()

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["status"] == 503
    assert events[0]["error_scope"] == "infrastructure"
    assert events[0]["message"].startswith("signer unavailable:")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("healthy", "status_code", "status"),
    [(True, 200, "ok"), (False, 503, "degraded")],
)
async def test_readiness_includes_signer_health(
    monkeypatch: pytest.MonkeyPatch,
    healthy: bool,
    status_code: int,
    status: str,
) -> None:
    monkeypatch.setattr(
        signer_service,
        "signer_is_healthy",
        AsyncMock(return_value=healthy),
    )

    response = await main.health()

    assert response.status_code == status_code
    assert json.loads(response.body)["status"] == status


@pytest.mark.parametrize(
    ("message", "scope", "expected"),
    [
        (SIGNER_ERROR, None, "infrastructure"),
        (" SIGNER UNAVAILABLE ", None, "infrastructure"),
        ("signer error: wasm failed", "infrastructure", "infrastructure"),
        ("upstream mentioned signer unavailable: x", None, "account"),
        ("10605 model queued", None, "model_queue"),
        ("quota exceeded", None, "quota"),
        ("upstream HTTP 401: unauthorized", None, "account"),
    ],
)
def test_chat_error_classification(
    message: str,
    scope: str | None,
    expected: str,
) -> None:
    assert chat.classify_chat_error(message, scope) == expected


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 8010),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_pre_response_signer_failure_does_not_fail_or_swap_account(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    account = SimpleNamespace(id=7, pat_token="pat-test")
    get_next = AsyncMock(return_value=account)
    mark_failure = AsyncMock()
    mark_quota = AsyncMock()
    monkeypatch.setattr(chat.pool, "get_next_account", get_next)
    monkeypatch.setattr(chat.pool, "mark_failure", mark_failure)
    monkeypatch.setattr(chat.pool, "mark_quota_exceeded", mark_quota)

    async def failing_infer(*args, **kwargs):
        yield {
            "type": "error",
            "message": SIGNER_ERROR,
            "status": 503,
            "error_scope": "infrastructure",
        }

    monkeypatch.setattr(direct_client, "run_infer", failing_infer)
    body = ChatCompletionRequest(
        model="kmodel_latest",
        messages=[{"role": "user", "content": "hello"}],
        stream=stream,
    )

    with pytest.raises(HTTPException) as raised:
        await chat.chat_completions(body, _request(), AsyncMock())

    assert raised.value.status_code == 503
    assert raised.value.detail == SIGNER_ERROR
    assert get_next.await_count == 1
    mark_failure.assert_not_awaited()
    mark_quota.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_account_error_still_marks_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(id=7, pat_token="pat-test")
    mark_failure = AsyncMock()
    monkeypatch.setattr(
        chat.pool,
        "get_next_account",
        AsyncMock(return_value=account),
    )
    monkeypatch.setattr(chat.pool, "mark_failure", mark_failure)

    message = "upstream HTTP 401: unauthorized"

    async def failing_infer(*args, **kwargs):
        yield {"type": "error", "message": message}

    monkeypatch.setattr(direct_client, "run_infer", failing_infer)
    body = ChatCompletionRequest(
        model="kmodel_latest",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    with pytest.raises(HTTPException) as raised:
        await chat.chat_completions(body, _request(), AsyncMock())

    assert raised.value.status_code == 502
    mark_failure.assert_awaited_once_with(7, message)


@pytest.mark.asyncio
async def test_midstream_signer_failure_does_not_fail_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_failure = AsyncMock()
    mark_quota = AsyncMock()
    monkeypatch.setattr(chat.pool, "mark_failure", mark_failure)
    monkeypatch.setattr(chat.pool, "mark_quota_exceeded", mark_quota)

    async def remaining_events():
        yield {
            "type": "error",
            "message": SIGNER_ERROR,
            "error_scope": "infrastructure",
        }

    response = chat._sse_response(
        7,
        "kmodel_latest",
        "kmodel_latest",
        remaining_events(),
        {"type": "text", "text": "started"},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    assert SIGNER_ERROR in payload
    assert "data: [DONE]" in payload
    mark_failure.assert_not_awaited()
    mark_quota.assert_not_awaited()
