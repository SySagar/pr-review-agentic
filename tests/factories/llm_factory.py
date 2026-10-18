"""Factories for LLM client, transport, and error tests.

Tests build LLM fixtures through these functions instead of constructing fake
clients, responses, or settings inline. This keeps test bodies focused on the
behavior under test and gives one place to change when the LLM layer evolves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from harness.config import Settings
from harness.llm import LLMClient
from tests.factories.config_factory import build_settings

DEFAULT_LLM_API_KEY = "sk-super-secret-value"
DEFAULT_LLM_MODEL = "test-model"


class FakeHTTPError(Exception):
    """Fake provider error carrying an HTTP status code."""

    def __init__(self, status_code: int = 429, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


class FakeCompletions:
    """Scripted ``client.chat.completions`` endpoint."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("unexpected LLM call")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeAsyncClient:
    """Fake ``AsyncOpenAI`` instance for transport tests."""

    def __init__(self, *responses: Any) -> None:
        self.completions = FakeCompletions(list(responses))
        self.chat = SimpleNamespace(completions=self.completions)


class FakeTransport:
    """Fake ``ChatTransport`` port for client tests."""

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> Any:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("unexpected LLM call")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@dataclass
class LLMHarness:
    """Bundle of the client under test plus its fakes and recorded delays."""

    client: LLMClient
    transport: FakeTransport
    delays: list[float] = field(default_factory=list)


def build_llm_settings(**env: str) -> Settings:
    """Build settings with a default test key and model, allowing overrides."""

    values = {"LLM_API_KEY": DEFAULT_LLM_API_KEY, "LLM_MODEL": DEFAULT_LLM_MODEL}
    values.update(env)
    return build_settings(_env=values)


def build_http_error(status_code: int = 429, message: str = "boom") -> FakeHTTPError:
    return FakeHTTPError(status_code=status_code, message=message)


def build_llm_response(content: str | None = '{"ok": true}') -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def build_fake_async_client(*responses: Any) -> FakeAsyncClient:
    return FakeAsyncClient(*responses)


def build_capturing_async_openai(captured: dict[str, Any]) -> type:
    """Return an ``AsyncOpenAI`` stand-in that records constructor kwargs."""

    class _CapturingAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    return _CapturingAsyncOpenAI


def build_llm_harness(
    *responses: Any,
    settings: Settings | None = None,
    max_retries: int = 2,
    base_backoff_seconds: float = 0.5,
) -> LLMHarness:
    """Build an ``LLMClient`` wired to a fake transport and recording sleep."""

    transport = FakeTransport(*responses)
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    client = LLMClient(
        settings or build_llm_settings(),
        transport=transport,
        sleep=sleep,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
    )
    return LLMHarness(client=client, transport=transport, delays=delays)
