"""Domain errors and provider-error classification for the LLM layer.

Error types live here so callers (agents, orchestrator) can map failures to
statuses without importing the transport or client implementation.
"""

from __future__ import annotations

import asyncio

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

__all__ = [
    "LLMError",
    "LLMResponseError",
    "RateLimitExhausted",
    "http_status",
    "is_rate_limit",
    "is_retryable",
]


class LLMError(Exception):
    """Base class for LLM failures that callers can map to agent statuses."""


class RateLimitExhausted(LLMError):
    """Raised when HTTP 429 persists after the configured retries."""


class LLMResponseError(LLMError):
    """Raised when the model response is not a single JSON object."""


def http_status(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an SDK or fake transport exception."""

    code = getattr(exc, "status_code", None)
    if code is None:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def is_rate_limit(exc: BaseException) -> bool:
    """Return True when the provider signalled HTTP 429."""

    return http_status(exc) == 429 or isinstance(exc, RateLimitError)


def is_retryable(exc: BaseException) -> bool:
    """Return True for 429, 5xx, timeout, and connection failures."""

    if is_rate_limit(exc):
        return True
    if isinstance(
        exc,
        (
            InternalServerError,
            APITimeoutError,
            APIConnectionError,
            asyncio.TimeoutError,
            TimeoutError,
        ),
    ):
        return True
    status = http_status(exc)
    return status is not None and 500 <= status <= 599
