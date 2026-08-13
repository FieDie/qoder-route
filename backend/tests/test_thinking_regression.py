from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

from app.api import chat
from app.models.schemas import ChatCompletionRequest
from app.services import direct_client
from app.services import model_probe
from app.services.qoder_client import QODER_MODEL_DISPLAY, resolve_model_level


def test_qwen_38_max_uses_canonical_model_key_and_long_context() -> None:
    model_key = resolve_model_level("qoder/qwen3.8-max")

    assert model_key == "qmodel_38max"
    assert direct_client.MODEL_KEY_MAP[model_key] == "qmodel_38max"

    body = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": "hello"}],
            model_key=model_key,
            tools=None,
        )
    )

    assert body["model_config"] == {
        "key": "qmodel_38max",
        "display_name": "Qwen3.8-Max",
        "model": "",
        "format": "openai",
        "is_vl": True,
        "api_key": "",
        "url": "",
        "max_input_tokens": 180_000,
        "is_reasoning": True,
        "source": "system",
    }
    assert body["chat_context"]["extra"]["modelConfig"] == {
        "key": "qmodel_38max",
        "is_reasoning": True,
    }
    assert body["parameters"]["context_length"] == 1_000_000
    assert "enable_thinking" not in body["parameters"]
    assert "reasoning_effort" not in body["parameters"]
    assert "preserve_thinking" not in body["parameters"]
    assert body["business"]["product"] == "cli"
    assert body["business"]["version"] == "1.1.17"
    assert body["business"]["type"] == "agent"
    assert body["business"]["name"] == "hello"
    assert body["business"]["stage"] == "start"
    assert isinstance(body["business"]["id"], str)
    assert isinstance(body["business"]["begin_at"], int)
    assert body["session_type"] == "qodercli"


def test_qwen_preview_remains_a_distinct_internal_model() -> None:
    assert resolve_model_level("qmodel_preview") == "qmodel_preview"
    assert resolve_model_level("qoder/qmodel_preview") == "qmodel_preview"
    assert direct_client.MODEL_KEY_MAP["qmodel_preview"] == "qmodel_preview"


def test_cantus_uses_its_own_canonical_model_not_glm() -> None:
    model_key = resolve_model_level("qoder/Cantus")

    assert model_key == "cmodel"
    assert model_key != resolve_model_level("GLM-5.2")
    assert direct_client.MODEL_KEY_MAP[model_key] == "cmodel"

    body = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": "hello"}],
            model_key=model_key,
            tools=None,
        )
    )

    assert body["model_config"] == {
        "key": "cmodel",
        "display_name": "Cantus",
        "model": "",
        "format": "openai",
        "is_vl": True,
        "api_key": "",
        "url": "",
        "max_input_tokens": 180_000,
        "source": "system",
        "is_reasoning": True,
    }
    assert body["chat_context"]["extra"]["modelConfig"] == {
        "key": "cmodel",
        "is_reasoning": True,
    }
    assert body["parameters"]["context_length"] == 1_000_000
    assert body["parameters"]["reasoning_effort"] == "max"
    assert body["parameters"]["enable_thinking"] is True
    assert ("Cantus", "cmodel") not in model_probe._probe_models()


def test_infer_endpoint_setting_overrides_qoder_cli_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    endpoint_cache = tmp_path / "endpoint-cache.json"
    endpoint_cache.write_text(
        json.dumps(
            {
                "entries": {
                    "prod": {
                        "endpoint": "https://api2.qoder.sh",
                        "inferEndpoints": ["https://api3.qoder.sh"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(direct_client, "INFER_BASE", "")
    monkeypatch.setattr(direct_client, "INFER_ENDPOINT_CACHE", endpoint_cache)
    monkeypatch.setattr(
        direct_client.settings_service,
        "get_qoder_infer_base",
        lambda: "api2",
    )

    assert direct_client._resolve_infer_base() == "https://api2.qoder.sh"


def test_infer_endpoint_operator_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct_client, "INFER_BASE", "https://api1.qoder.sh/")
    monkeypatch.setattr(
        direct_client.settings_service,
        "get_qoder_infer_base",
        lambda: "api2",
    )

    assert direct_client._resolve_infer_base() == "https://api1.qoder.sh"


def test_infer_endpoint_rejects_unallowlisted_operator_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct_client, "INFER_BASE", "https://api7.qoder.sh/")
    monkeypatch.setattr(
        direct_client.settings_service,
        "get_qoder_infer_base",
        lambda: "api2",
    )

    assert direct_client._resolve_infer_base() == "https://api2.qoder.sh"


@pytest.mark.asyncio
async def test_qwen_38_uses_native_endpoint_and_transport_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer_payload: dict = {}
    upstream_request: dict = {}

    async def signer_handler(request: httpx.Request) -> httpx.Response:
        signer_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "body_b64": "",
                "headers": {
                    "Accept": "text/event-stream",
                    "Cosy-Version": "1.1.17",
                    "Cosy-ClientType": "5",
                },
                "url": (
                    "https://api3.qoder.sh/algo/api/v2/service/pro/sse/"
                    "agent_chat_generation?FetchKeys=llm_model_result&"
                    "AgentId=agent_common&Encode=1"
                ),
            },
        )

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        upstream_request["url"] = str(request.url)
        upstream_request["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            text="data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    signer = httpx.AsyncClient(transport=httpx.MockTransport(signer_handler))
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
    monkeypatch.setattr(direct_client, "get_job_token", AsyncMock(return_value="jt-test"))
    monkeypatch.setattr(direct_client, "get_uid", AsyncMock(return_value="uid-test"))
    monkeypatch.setattr(direct_client, "_get_signer", lambda: signer)
    monkeypatch.setattr(direct_client, "_get_upstream", lambda: upstream)
    monkeypatch.setattr(direct_client, "INFER_BASE", "https://api3.qoder.sh")
    try:
        events = [
            event
            async for event in direct_client.run_infer(
                "pat-test",
                "qmodel_38max",
                [{"role": "user", "content": "hello"}],
            )
        ]
    finally:
        await signer.aclose()
        await upstream.aclose()

    assert events[-1]["type"] == "done"
    assert signer_payload["base_url"] == "https://api3.qoder.sh"
    assert signer_payload["model_key"] == "qmodel_38max"
    signed_body = json.loads(signer_payload["body_json"])
    assert signed_body["model_config"]["key"] == "qmodel_38max"
    assert signed_body["session_type"] == "qodercli"
    assert signed_body["business"]["product"] == "cli"
    assert signed_body["business"]["type"] == "agent"
    assert upstream_request["url"].startswith("https://api3.qoder.sh/")
    headers = upstream_request["headers"]
    assert headers["user-agent"] == "Bun/1.3.14"
    assert headers["cosy-clienttype"] == "5"
    assert headers["cosy-machineos"] == "x86_64_linux"
    assert re.fullmatch(
        r"00-[0-9a-f]{32}-[0-9a-f]{16}-01",
        headers["traceparent"],
    )


@pytest.mark.parametrize("display_name,model_key", QODER_MODEL_DISPLAY)
def test_every_advertised_model_id_round_trips(
    display_name: str,
    model_key: str,
) -> None:
    assert resolve_model_level(model_key) == model_key
    assert resolve_model_level(f"qoder/{model_key}") == model_key
    assert resolve_model_level(display_name) == model_key


def test_large_context_request_keeps_thinking_enabled() -> None:
    # Large enough to catch any size-based request rewriting without making the
    # unit test depend on a model-specific tokenizer.
    long_history = "long-context-token " * 50_000

    body = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": long_history}],
            model_key="qmodel_latest",
            tools=None,
            reasoning_effort="max",
            context_window=1_000_000,
        )
    )

    assert body["messages"][0]["content"] == long_history
    assert "context_window" not in body["model_config"]
    # Qwen3.7-Max can emit thinking through enable_thinking, but the native
    # catalog declares the model capability itself as non-reasoning.
    assert body["model_config"]["is_reasoning"] is False
    assert body["chat_context"]["extra"]["modelConfig"] == {
        "key": "qmodel_latest",
        "is_reasoning": False,
    }
    assert body["parameters"]["context_length"] == 1_000_000
    assert body["parameters"]["max_tokens"] == 32_000
    assert body["parameters"]["reasoning_effort"] == "max"
    assert body["parameters"]["enable_thinking"] is True
    assert "preserve_thinking" not in body["parameters"]
    assert "reasoning_budget_tokens" not in body["parameters"]


def test_large_context_preserves_reasoning_history() -> None:
    body = json.loads(
        direct_client._build_body(
            messages=[
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "previous reasoning",
                    "reasoning_content_signature": "signed-reasoning",
                    "reasoning_item": {"id": "reasoning-1"},
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "inspect", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "result"},
                {"role": "user", "content": "next question"},
            ],
            model_key="kmodel_latest",
            tools=None,
            context_window=1_000_000,
        )
    )

    assistant = body["messages"][0]
    assert assistant["reasoning_content"] == "previous reasoning"
    assert assistant["reasoning_content_signature"] == "signed-reasoning"
    assert assistant["reasoning_item"] == {"id": "reasoning-1"}
    assert assistant["tool_calls"][0]["id"] == "call-1"
    assert body["messages"][1]["tool_call_id"] == "call-1"


def test_auto_uses_its_supported_default_context_window() -> None:
    body = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": "hello"}],
            model_key="auto",
            tools=None,
        )
    )

    assert body["parameters"]["context_length"] == 180_000


def test_client_session_id_is_reused_in_qoder_body() -> None:
    session_id = "ses_01e3cb8afffenHVl16OzS39Dtz"

    first = json.loads(
        direct_client._build_body(
            messages=[{"role": "user", "content": "first"}],
            model_key="kmodel_latest",
            tools=None,
            session_id=session_id,
        )
    )
    next_turn = json.loads(
        direct_client._build_body(
            messages=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": ""},
                {"role": "tool", "content": "result", "tool_call_id": "call-1"},
            ],
            model_key="kmodel_latest",
            tools=None,
            session_id=session_id,
        )
    )

    assert first["session_id"] == session_id
    assert next_turn["session_id"] == session_id
    assert first["request_id"] != next_turn["request_id"]
    assert first["chat_record_id"] == first["request_id"]
    assert next_turn["chat_record_id"] == next_turn["request_id"]


def test_opencode_session_header_is_validated() -> None:
    assert chat._client_session_id(
        {"x-session-id": "ses_01e3cb8afffenHVl16OzS39Dtz"}
    ) == "ses_01e3cb8afffenHVl16OzS39Dtz"
    assert chat._client_session_id(
        {"x-session-affinity": "ses_fallback"}
    ) == "ses_fallback"
    assert chat._client_session_id({"x-session-id": "bad session\nvalue"}) is None


def test_native_system_and_chat_context_shape_is_preserved() -> None:
    body = json.loads(
        direct_client._build_body(
            messages=[
                {"role": "system", "content": "first system"},
                {"role": "system", "content": "second system"},
                {"role": "user", "content": "original task"},
                {"role": "assistant", "content": "working"},
                {"role": "tool", "content": "tool result", "tool_call_id": "call-1"},
            ],
            model_key="kmodel_latest",
            tools=None,
            session_id="ses_context_shape",
        )
    )

    assert body["system"] == "first system\n\nsecond system"
    assert body["messages"][0] == {
        "role": "system",
        "content": "first system\n\nsecond system",
    }
    assert body["chat_context"] == {
        "text": "original task",
        "features": [],
        "extra": {
            "context": [],
            "modelConfig": {"key": "kmodel_latest", "is_reasoning": False},
            "originalContent": "original task",
        },
        "chatPrompt": "",
        "imageUrls": None,
    }
    assert body["model_config"]["is_reasoning"] is False
    assert body["parameters"]["enable_thinking"] is True
    assert body["parameters"]["reasoning_effort"] == "max"


def test_multimodal_user_text_wins_over_previous_string_chat_context() -> None:
    body = json.loads(
        direct_client._build_body(
            messages=[
                {"role": "user", "content": "old prompt"},
                {"role": "assistant", "content": "old answer"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "remove this line"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,abc"},
                        },
                    ],
                },
            ],
            model_key="kmodel_latest",
            tools=None,
            session_id="ses_multimodal_context",
        )
    )

    assert body["chat_context"]["text"] == "remove this line"
    assert body["chat_context"]["extra"]["originalContent"] == "remove this line"


def test_output_limit_and_reasoning_blocks_survive_request_normalization() -> None:
    request = ChatCompletionRequest(
        model="kimi-k3",
        max_tokens=12_345,
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "visible ",
                    },
                    {
                        "type": "thinking",
                        "thinking": "history",
                        "signature": "history-signature",
                    },
                    {"type": "text", "text": "previous answer"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "redacted_thinking",
                        "data": "encrypted-history",
                        "reasoning_item": {
                            "id": "opaque-reasoning-1",
                            "type": "reasoning",
                            "encrypted_content": "stale-state",
                        },
                    },
                ],
            },
        ],
    )
    body = json.loads(
        direct_client._build_body(
            messages=[message.model_dump() for message in request.messages],
            model_key="kmodel_latest",
            tools=None,
            max_tokens=request.max_tokens,
        )
    )

    assert body["parameters"]["max_tokens"] == 12_345
    assert body["messages"][0]["reasoning_content"] == "visible history"
    assert body["messages"][0]["reasoning_content_signature"] == "history-signature"
    assert body["messages"][0]["reasoning_item"] == {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "visible history"}],
    }
    assert body["messages"][1]["reasoning_item"] == {
        "id": "opaque-reasoning-1",
        "type": "reasoning",
        "encrypted_content": "encrypted-history",
    }


@pytest.mark.asyncio
async def test_high_prompt_usage_does_not_filter_reasoning_delta() -> None:
    usage: dict = {}
    upstream_chunk = {
        "usage": {
            "prompt_tokens": 900_000,
            "completion_tokens": 12,
            "total_tokens": 900_012,
        },
        "choices": [
            {
                "delta": {
                    "reasoning_content": "still thinking at high context",
                    "content": "answer",
                }
            }
        ],
    }

    events = [event async for event in direct_client._emit_chunk(upstream_chunk, usage)]

    assert events == [
        {"type": "thinking", "thinking": "still thinking at high context"},
        {"type": "text", "text": "answer"},
    ]
    assert usage["prompt_tokens"] == 900_000


@pytest.mark.asyncio
async def test_message_reasoning_item_summary_and_signature_are_not_dropped() -> None:
    usage: dict = {}
    reasoning_item = {
        "id": "reasoning-1",
        "type": "reasoning",
        "summary": [
            {"type": "summary_text", "text": "summary "},
            {"type": "summary_text", "text": "thinking"},
        ],
        "encrypted_content": "opaque-state",
    }
    upstream_chunk = {
        "choices": [
            {
                "delta": {},
                "message": {
                    "reasoning_item": reasoning_item,
                    "signature": "signed-state",
                    "content": "answer",
                }
            }
        ]
    }

    events = [event async for event in direct_client._emit_chunk(upstream_chunk, usage)]

    assert events == [
        {"type": "thinking", "thinking": "summary thinking"},
        {"type": "reasoning_item", "reasoning_item": reasoning_item},
        {"type": "reasoning_signature", "signature": "signed-state"},
        {"type": "text", "text": "answer"},
    ]


async def _mocked_upstream_events(
    monkeypatch: pytest.MonkeyPatch,
    stream_body: str,
) -> list[dict]:
    async def signer_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "body_b64": "",
                "headers": {},
                "url": "https://upstream.test/infer",
            },
        )

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=stream_body,
            headers={"content-type": "text/event-stream"},
        )

    signer = httpx.AsyncClient(transport=httpx.MockTransport(signer_handler))
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
    monkeypatch.setattr(direct_client, "get_job_token", AsyncMock(return_value="jt-test"))
    monkeypatch.setattr(direct_client, "get_uid", AsyncMock(return_value="uid-test"))
    monkeypatch.setattr(direct_client, "_get_signer", lambda: signer)
    monkeypatch.setattr(direct_client, "_get_upstream", lambda: upstream)
    try:
        return [
            event
            async for event in direct_client.run_infer(
                "pat-test",
                "kmodel_latest",
                [{"role": "user", "content": "hello"}],
            )
        ]
    finally:
        await signer.aclose()
        await upstream.aclose()


@pytest.mark.asyncio
async def test_truncated_sse_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _mocked_upstream_events(
        monkeypatch,
        'data: {"choices":[{"delta":{"reasoning_content":"partial"}}]}\r\n',
    )

    assert events[0] == {"type": "thinking", "thinking": "partial"}
    assert events[-1]["type"] == "error"
    assert "ended before" in events[-1]["message"]
    assert not any(event["type"] == "done" for event in events)


@pytest.mark.asyncio
async def test_finish_reason_completes_crlf_sse_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _mocked_upstream_events(
        monkeypatch,
        'data: {"choices":[{"delta":{"content":"answer"},'
        '"finish_reason":"stop"}]}\r\n',
    )

    assert events[0] == {"type": "text", "text": "answer"}
    assert events[1]["type"] == "done"
    assert events[1]["usage"] == {}
    assert events[1]["diagnostics"]["upstream_finish_reasons"] == "stop"
    assert "content" in events[1]["diagnostics"]["upstream_payload_keys"]


@pytest.mark.asyncio
async def test_upstream_sse_error_is_not_reported_as_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _mocked_upstream_events(
        monkeypatch,
        'data: {"body":{"error":{"message":"model stream failed"}}}\n\n',
    )

    assert events == [{"type": "error", "message": "model stream failed"}]


@pytest.mark.asyncio
async def test_usage_only_sse_event_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _mocked_upstream_events(
        monkeypatch,
        'data: {"usage":{"prompt_tokens":280000,"completion_tokens":42,'
        '"total_tokens":280042}}\n\ndata: [DONE]\n\n',
    )

    assert events[-1]["type"] == "done"
    assert events[-1]["usage"]["prompt_tokens"] == 280_000


@pytest.mark.asyncio
async def test_non_200_sse_wrapper_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _mocked_upstream_events(
        monkeypatch,
        'data: {"statusCodeValue":429,"body":{"message":"rate limited"}}\n\n',
    )

    assert events == [{"type": "error", "status": 429, "message": "upstream status 429: rate limited"}]


def test_tool_call_stream_fragments_are_assembled_for_json_response() -> None:
    accumulator: dict[int, dict] = {}
    chat._merge_tool_call_fragments(
        accumulator,
        [{"index": 0, "id": "call_1", "function": {"name": "get_", "arguments": '{"ci'}}],
    )
    chat._merge_tool_call_fragments(
        accumulator,
        [{"index": 0, "function": {"name": "weather", "arguments": 'ty":"Paris"}'}}],
    )

    assert chat._finalize_tool_calls(accumulator) == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
        }
    ]


@pytest.mark.asyncio
async def test_openai_sse_keeps_thinking_block_for_large_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_history = "context " * 100_000
    messages = [{"role": "user", "content": long_history}]
    captured: dict = {}

    async def fake_run_infer(
        pat: str,
        model_level: str,
        request_messages: list[dict],
        tools: list[dict] | None,
        reasoning_effort: str | None,
        fast: bool | None,
        context_window: int | None,
        max_tokens: int | None,
        session_id: str | None,
    ):
        captured.update(
            pat=pat,
            model_level=model_level,
            messages=request_messages,
            reasoning_effort=reasoning_effort,
            context_window=context_window,
            max_tokens=max_tokens,
            session_id=session_id,
        )
        yield {"type": "thinking", "thinking": "reasoning survives"}
        yield {
            "type": "reasoning_item",
            "reasoning_item": {"id": "reasoning-1", "encrypted_content": "opaque"},
        }
        yield {"type": "reasoning_signature", "signature": "signed-state"}
        yield {"type": "text", "text": "final answer"}
        yield {
            "type": "done",
            "usage": {
                "prompt_tokens": 900_000,
                "completion_tokens": 20,
                "total_tokens": 900_020,
            },
        }

    mark_success = AsyncMock()
    monkeypatch.setattr(chat.direct_client, "run_infer", fake_run_infer)
    monkeypatch.setattr(chat.pool, "mark_success", mark_success)
    monkeypatch.setattr(chat.logbus, "push", lambda *args, **kwargs: None)

    # Mirror the endpoint's streaming flow: start the generator and pull the
    # first event, then hand (gen, first) to _sse_response.
    gen = fake_run_infer(
        "test-pat",
        "qmodel_latest",
        messages,
        None,
        "max",
        None,
        1_000_000,
        12_345,
        "ses_large_context",
    )
    first = await gen.__anext__()

    response = chat._sse_response(
        account_id=7,
        model_level="qmodel_latest",
        model="qmodel_latest",
        gen=gen,
        first_event=first,
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    stream = "".join(chunks)
    payloads = [
        json.loads(frame.removeprefix("data: "))
        for frame in stream.split("\n\n")
        if frame.startswith("data: ") and frame != "data: [DONE]"
    ]

    assert captured["messages"] is messages
    assert captured["reasoning_effort"] == "max"
    assert captured["context_window"] == 1_000_000
    assert captured["max_tokens"] == 12_345
    assert captured["session_id"] == "ses_large_context"
    assert any(
        payload["choices"][0]["delta"].get("reasoning_content")
        == "reasoning survives"
        for payload in payloads
    )
    assert any(
        payload["choices"][0]["delta"].get("reasoning_item", {}).get("id")
        == "reasoning-1"
        for payload in payloads
    )
    assert any(
        payload["choices"][0]["delta"].get("signature") == "signed-state"
        and payload["choices"][0]["delta"].get("reasoning_content_signature")
        == "signed-state"
        for payload in payloads
    )
    assert payloads[-1]["usage"]["prompt_tokens"] == 900_000
    assert stream.endswith("data: [DONE]\n\n")
    mark_success.assert_awaited_once_with(7, 20, 0.0, "qmodel_latest")


@pytest.mark.asyncio
async def test_non_streaming_response_keeps_reasoning_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(id=7, pat_token="test-pat")

    async def fake_run_infer(*args, **kwargs):
        yield {"type": "thinking", "thinking": "reasoning survives"}
        yield {
            "type": "reasoning_item",
            "reasoning_item": {"id": "reasoning-1", "encrypted_content": "opaque"},
        }
        yield {"type": "reasoning_signature", "signature": "signed-state"}
        yield {"type": "text", "text": "final answer"}
        yield {
            "type": "done",
            "usage": {
                "prompt_tokens": 250_000,
                "completion_tokens": 20,
                "total_tokens": 250_020,
            },
        }

    get_next_account = AsyncMock(return_value=account)
    mark_success = AsyncMock()
    monkeypatch.setattr(chat.pool, "get_next_account", get_next_account)
    monkeypatch.setattr(chat.pool, "mark_success", mark_success)
    monkeypatch.setattr(chat.direct_client, "run_infer", fake_run_infer)
    monkeypatch.setattr(chat.logbus, "push", lambda *args, **kwargs: None)

    response = await chat.chat_completions(
        ChatCompletionRequest(
            model="kimi-k3",
            messages=[{"role": "user", "content": "hello"}],
            stream=False,
            context_window=1_000_000,
        ),
        request=Request({"type": "http", "headers": [(b"x-session-id", b"ses_nonstream")]}),
        db=object(),
    )

    message = response.choices[0]["message"]
    assert message["content"] == "final answer"
    assert message["reasoning_content"] == "reasoning survives"
    assert message["reasoning_item"]["id"] == "reasoning-1"
    assert message["signature"] == "signed-state"
    assert message["reasoning_content_signature"] == "signed-state"
    mark_success.assert_awaited_once_with(7, 20, 0.0, "kmodel_latest")
