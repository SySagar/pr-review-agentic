"""Transport layer for OpenAI-compatible chat completion APIs.

The transport owns the HTTP client and request shape. It knows nothing about
retries, telemetry, or JSON validation; those belong to :mod:`harness.llm`.
Swapping the underlying SDK or provider happens here, behind :class:`ChatTransport`.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from openai import AsyncOpenAI

from harness.config import Settings
from harness.errors import http_status

logger = logging.getLogger(__name__)

__all__ = ["ChatTransport", "OpenAICompatibleTransport"]


class ChatTransport(Protocol):
    """Interface for a provider-specific chat completion transport."""

    async def complete(self, messages: list[dict[str, str]]) -> Any:
        """Send messages and return the raw provider response."""
        ...


class OpenAICompatibleTransport:
    """Concrete transport backed by the official ``openai`` async SDK."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        api_key = settings.llm_api_key.get_secret_value()
        self._model = settings.llm_model
        self._client = client or AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=api_key or "not-needed",
        )
        self._json_mode = True

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, messages: list[dict[str, str]]) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.0,
        }
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            return await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Some compatible providers reject JSON mode. Fall back once and
            # keep the flag off for the rest of the transport's lifetime.
            if self._json_mode and http_status(exc) == 400 and "response_format" in str(exc):
                logger.info("Provider rejected JSON response_format; retrying without it")
                self._json_mode = False
                kwargs.pop("response_format", None)
                return await self._client.chat.completions.create(**kwargs)
            raise
