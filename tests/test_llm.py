"""Unit tests for the LLM client, transport, and error classification.

All fixtures come from ``tests/factories/llm_factory.py``; no real network calls
are made. Fakes stand in for the OpenAI SDK and for the transport port.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from harness.errors import LLMError, LLMResponseError, RateLimitExhausted
from harness.llm import LLMClient, extract_json_object
from harness.llm_transport import OpenAICompatibleTransport
from tests.factories import (
    DEFAULT_LLM_API_KEY as SECRET,
)
from tests.factories import (
    build_capturing_async_openai,
    build_fake_async_client,
    build_http_error,
    build_llm_harness,
    build_llm_response,
    build_llm_settings,
)


def test_settings_configure_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider swapping relies only on Settings, not hard-coded values."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "harness.llm_transport.AsyncOpenAI",
        build_capturing_async_openai(captured),
    )

    settings = build_llm_settings(
        LLM_BASE_URL="https://example.test/v1/",
        LLM_MODEL="other-model",
    )
    transport = OpenAICompatibleTransport(settings)

    assert captured == {"base_url": "https://example.test/v1/", "api_key": SECRET}
    assert transport.model == "other-model"


def test_transport_sends_json_mode_request() -> None:
    """The transport builds the provider request and requests JSON mode."""
    messages = [{"role": "user", "content": "hello"}]
    fake = build_fake_async_client(build_llm_response())
    transport = OpenAICompatibleTransport(build_llm_settings(), client=fake)

    response = asyncio.run(transport.complete(messages))

    assert response.choices[0].message.content == '{"ok": true}'
    call = fake.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["messages"] == messages
    assert call["temperature"] == 0.0
    assert call["response_format"] == {"type": "json_object"}


def test_transport_falls_back_when_provider_rejects_json_mode() -> None:
    """A provider that rejects response_format is retried once without it."""
    fake = build_fake_async_client(
        build_http_error(400, "response_format is not supported"),
        build_llm_response(),
    )
    transport = OpenAICompatibleTransport(build_llm_settings(), client=fake)

    result = asyncio.run(transport.complete([{"role": "user", "content": "hi"}]))

    assert result.choices[0].message.content == '{"ok": true}'
    assert len(fake.completions.calls) == 2
    assert "response_format" not in fake.completions.calls[1]


def test_chat_json_builds_messages_and_returns_object() -> None:
    """The client sends system/user messages and parses the JSON object."""
    harness = build_llm_harness(build_llm_response())

    result = asyncio.run(harness.client.chat_json("system prompt", "user prompt"))

    assert result == {"ok": True}
    assert harness.delays == []
    assert harness.transport.calls == [
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
        ]
    ]


def test_429_then_success_retries_with_backoff() -> None:
    """One 429 should be absorbed by exactly one retry."""
    harness = build_llm_harness(
        build_http_error(429),
        build_llm_response('{"ok": true}'),
    )

    result = asyncio.run(harness.client.chat_json("s", "u"))

    assert result == {"ok": True}
    assert len(harness.transport.calls) == 2
    assert harness.delays == [0.5]
    assert harness.client.stats.retries == 1
    assert harness.client.stats.calls == 1


def test_exhausted_429_raises_rate_limit_exhausted() -> None:
    """Three 429 responses (two retries) end in RateLimitExhausted."""
    harness = build_llm_harness(
        build_http_error(429),
        build_http_error(429),
        build_http_error(429),
    )

    with pytest.raises(RateLimitExhausted):
        asyncio.run(harness.client.chat_json("s", "u"))

    assert len(harness.transport.calls) == 3
    assert harness.delays == [0.5, 1.0]
    assert harness.client.stats.retries == 2
    assert harness.client.stats.calls == 0


def test_exhausted_5xx_raises_generic_llm_error() -> None:
    """A persistent 5xx is terminal but is not a rate-limit signal."""
    harness = build_llm_harness(
        build_http_error(503),
        build_http_error(503),
        build_http_error(502),
    )

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(harness.client.chat_json("s", "u"))

    assert not isinstance(exc_info.value, RateLimitExhausted)
    assert harness.delays == [0.5, 1.0]


def test_timeout_is_retried_then_raises_llm_error() -> None:
    """Timeouts use the same retry loop as 5xx responses."""
    harness = build_llm_harness(TimeoutError(), TimeoutError(), TimeoutError())

    with pytest.raises(LLMError):
        asyncio.run(harness.client.chat_json("s", "u"))

    assert len(harness.transport.calls) == 3
    assert harness.delays == [0.5, 1.0]


def test_non_retryable_status_is_not_retried() -> None:
    """A 401 fails immediately with a generic LLMError."""
    harness = build_llm_harness(build_http_error(401, "unauthorized"))

    with pytest.raises(LLMError):
        asyncio.run(harness.client.chat_json("s", "u"))

    assert len(harness.transport.calls) == 1
    assert harness.delays == []


def test_zero_retries_fails_on_first_429() -> None:
    """A caller can disable retries entirely."""
    harness = build_llm_harness(build_http_error(429), max_retries=0)

    with pytest.raises(RateLimitExhausted):
        asyncio.run(harness.client.chat_json("s", "u"))

    assert len(harness.transport.calls) == 1
    assert harness.delays == []


def test_invalid_json_raises_typed_parse_error_without_retry() -> None:
    """Parse failures are the agent runtime's responsibility to retry."""
    harness = build_llm_harness(build_llm_response("this is not json"))

    with pytest.raises(LLMResponseError):
        asyncio.run(harness.client.chat_json("s", "u"))

    assert len(harness.transport.calls) == 1
    assert harness.client.stats.retries == 0
    assert harness.client.stats.calls == 1


def test_non_object_json_is_rejected() -> None:
    """The contract is one JSON object, so arrays and scalars are invalid."""
    harness = build_llm_harness(build_llm_response("[1, 2, 3]"))

    with pytest.raises(LLMResponseError):
        asyncio.run(harness.client.chat_json("s", "u"))


def test_empty_content_is_rejected() -> None:
    """A missing message body is a typed parse error, not a crash."""
    harness = build_llm_harness(build_llm_response(None))

    with pytest.raises(LLMResponseError):
        asyncio.run(harness.client.chat_json("s", "u"))


def test_code_fences_are_stripped() -> None:
    """Models often wrap JSON in Markdown fences; strip them safely."""
    harness = build_llm_harness(build_llm_response('```json\n{"findings": []}\n```'))

    assert asyncio.run(harness.client.chat_json("s", "u")) == {"findings": []}


def test_first_object_is_extracted_from_surrounding_prose() -> None:
    """A short prose prefix/suffix should not break JSON extraction."""
    harness = build_llm_harness(build_llm_response('Here is the result: {"ok": true} — done'))

    assert asyncio.run(harness.client.chat_json("s", "u")) == {"ok": True}


def test_extract_json_object_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        extract_json_object("   ")


def test_calls_and_latency_are_accumulated() -> None:
    """Telemetry counts successful calls and non-negative latency."""
    harness = build_llm_harness(
        build_llm_response('{"a": 1}'),
        build_llm_response('{"b": 2}'),
    )

    asyncio.run(harness.client.chat_json("s", "u"))
    asyncio.run(harness.client.chat_json("s", "u"))

    stats = harness.client.stats
    assert stats.calls == 2
    assert stats.retries == 0
    assert stats.latency_ms >= 0


def test_stats_snapshot_cannot_mutate_client_state() -> None:
    """The stats property returns a copy, not the live dataclass."""
    harness = build_llm_harness(build_llm_response())

    asyncio.run(harness.client.chat_json("s", "u"))
    snapshot = harness.client.stats
    snapshot.calls = 99

    assert harness.client.stats.calls == 1


def test_secret_is_redacted_from_terminal_errors_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exception text and log records must never contain the API key."""
    caplog.set_level(logging.DEBUG)
    harness = build_llm_harness(
        build_http_error(500, f"server leaked {SECRET}"),
        build_http_error(500, f"server leaked {SECRET}"),
        build_http_error(500, f"server leaked {SECRET}"),
    )

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(harness.client.chat_json("s", "u"))

    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)
    assert all(SECRET not in record.getMessage() for record in caplog.records)


def test_invalid_retry_configuration_is_rejected() -> None:
    settings = build_llm_settings()

    with pytest.raises(ValueError):
        LLMClient(settings, max_retries=-1)
    with pytest.raises(ValueError):
        LLMClient(settings, base_backoff_seconds=-0.1)
