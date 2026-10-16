"""Environment-only configuration for the review harness.

Every component imports the same frozen :class:`Settings` object. Values come
from the process environment, with an optional local ``.env`` file loaded for
development. Secrets are stored as :class:`~pydantic.SecretStr` so they never
appear in ``repr`` output.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"
DEFAULT_AGENT_TIMEOUT_SECONDS = 90
DEFAULT_JUDGE_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_MAX_DIFF_LINES = 800
DEFAULT_DRY_RUN = False
DEFAULT_LOG_LEVEL = "INFO"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Environment variable name -> Settings field name.
_ENV_FIELDS: dict[str, str] = {
    "LLM_BASE_URL": "llm_base_url",
    "LLM_MODEL": "llm_model",
    "LLM_API_KEY": "llm_api_key",
    "GITHUB_TOKEN": "github_token",
    "GITHUB_PERSONAL_ACCESS_TOKEN": "github_personal_access_token",
    "AGENT_TIMEOUT_SECONDS": "agent_timeout_seconds",
    "JUDGE_CONFIDENCE_THRESHOLD": "judge_confidence_threshold",
    "MAX_DIFF_LINES": "max_diff_lines",
    "DRY_RUN": "dry_run",
    "LOG_LEVEL": "log_level",
    "GITHUB_MCP_PR_TOOL": "github_mcp_pr_tool",
    "GITHUB_MCP_DIFF_TOOL": "github_mcp_diff_tool",
    "GITHUB_MCP_COMMENT_TOOL": "github_mcp_comment_tool",
}


class Settings(BaseModel):
    """Validated runtime configuration.

    Construct with no arguments to read the process environment (and a local
    ``.env`` file). Pass ``_env`` with a mapping to read exactly that mapping,
    which keeps tests independent of the developer's shell and ``.env``.
    Explicit keyword arguments override environment values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    llm_base_url: str = Field(default=DEFAULT_LLM_BASE_URL, min_length=1)
    llm_model: str = Field(default=DEFAULT_LLM_MODEL, min_length=1)
    llm_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)

    github_token: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    github_personal_access_token: SecretStr = Field(
        default_factory=lambda: SecretStr(""), repr=False
    )

    agent_timeout_seconds: int = Field(default=DEFAULT_AGENT_TIMEOUT_SECONDS, gt=0)
    judge_confidence_threshold: float = Field(
        default=DEFAULT_JUDGE_CONFIDENCE_THRESHOLD, ge=0.0, le=1.0
    )
    max_diff_lines: int = Field(default=DEFAULT_MAX_DIFF_LINES, gt=0)
    dry_run: bool = DEFAULT_DRY_RUN
    log_level: LogLevel = DEFAULT_LOG_LEVEL

    # Optional tool-name overrides, applied after runtime discovery (Phase 12).
    github_mcp_pr_tool: str | None = None
    github_mcp_diff_tool: str | None = None
    github_mcp_comment_tool: str | None = None

    def __init__(self, _env: Mapping[str, str] | None = None, **data: Any) -> None:
        values = _read_env(_env)
        values.update(data)
        super().__init__(**values)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


def _read_env(env: Mapping[str, str] | None) -> dict[str, Any]:
    """Return known settings from an explicit mapping or process environment."""

    if env is None:
        _load_local_dotenv()
        source: Mapping[str, str] = os.environ
    else:
        source = env

    values: dict[str, Any] = {}
    for env_name, field_name in _ENV_FIELDS.items():
        raw = source.get(env_name)
        if raw is None or not raw.strip():
            continue
        values[field_name] = raw.strip()
    return values


def _load_local_dotenv() -> None:
    """Load ``.env`` from the current directory without overriding real env vars."""

    dotenv_path = Path.cwd() / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path=dotenv_path, override=False)


def load_settings() -> Settings:
    """Build settings from the process environment."""

    return Settings()
