"""Provider-agnostic async LLM client with retries, JSON parsing, and telemetry.

This module is the application layer: it builds prompts, applies the retry
policy, tracks calls and latency, and validates JSON. HTTP details live in
:mod:`harness.llm_transport`; error types live in :mod:`harness.errors`.

Retries are intentionally small and hand-rolled: at most two extra attempts for
HTTP 429, 5xx, and timeout/connection failures. Invalid JSON is *not* retried
here; the agent runtime owns the one-retry-with-validation-error rule.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from harness.config import Settings
from harness.errors import (
    LLMError,
    LLMResponseError,
    RateLimitExhausted,
    is_rate_limit,
    is_retryable,
)
from harness.llm_transport import ChatTransport, OpenAICompatibleTransport

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
BASE_BACKOFF_SECONDS = 0.5

__all__ = ["LLMClient", "LLMStats", "extract_json_object"]


@dataclass
class LLMStats:
    """Cumulative telemetry for one client instance."""

    calls: int = 0
    retries: int = 0
    latency_ms: int = 0


class LLMClient:
    """Async JSON-only client for any OpenAI-compatible chat completion API."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: ChatTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        max_retries: int = MAX_RETRIES,
        base_backoff_seconds: float = BASE_BACKOFF_SECONDS,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds must be non-negative")

        self._api_key = settings.llm_api_key.get_secret_value()
        self._transport = transport or OpenAICompatibleTransport(settings)
        self._sleep = sleep or asyncio.sleep
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._stats = LLMStats()

    @property
    def stats(self) -> LLMStats:
        """Immutable snapshot of the telemetry counters."""

        return replace(self._stats)

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send one JSON-only chat request and return the parsed object.

        Raises:
            RateLimitExhausted: HTTP 429 after all retries.
            LLMError: other terminal transport or provider failure.
            LLMResponseError: the response was not a single JSON object.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        started = time.perf_counter()
        attempt = 0

        while True:
            try:
                response = await self._transport.complete(messages)
            except Exception as exc:
                if is_retryable(exc) and attempt < self._max_retries:
                    attempt += 1
                    self._stats.retries += 1
                    delay = self._base_backoff_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM request failed (%s); retry %d/%d in %.2fs",
                        type(exc).__name__,
                        attempt,
                        self._max_retries,
                        delay,
                    )
                    await self._sleep(delay)
                    continue

                self._stats.latency_ms += _elapsed_ms(started)
                raise self._terminal_error(exc) from None

            self._stats.calls += 1
            self._stats.latency_ms += _elapsed_ms(started)
            return self._parse_content(response)

    def _parse_content(self, response: Any) -> dict[str, Any]:
        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMResponseError("LLM response contained no choices")

        content = getattr(getattr(choices[0], "message", None), "content", None)
        try:
            return extract_json_object(content)
        except (TypeError, ValueError):
            raise LLMResponseError("LLM response was not a single JSON object") from None

    def _terminal_error(self, exc: BaseException) -> LLMError:
        if is_rate_limit(exc):
            return RateLimitExhausted("LLM rate limit exhausted after retries")

        detail = str(exc)
        if self._api_key:
            detail = detail.replace(self._api_key, "[REDACTED]")
        return LLMError(f"LLM request failed ({type(exc).__name__}): {detail or 'no detail'}")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def extract_json_object(text: Any) -> dict[str, Any]:
    """Return one JSON object from model text, ignoring fences and prose."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("no JSON object found")

    value, _end = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(value, dict):
        raise ValueError("response is not a JSON object")
    return value
