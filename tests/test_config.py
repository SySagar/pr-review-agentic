from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.config import (
    DEFAULT_AGENT_TIMEOUT_SECONDS,
    DEFAULT_DRY_RUN,
    DEFAULT_JUDGE_CONFIDENCE_THRESHOLD,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_DIFF_LINES,
    Settings,
)
from tests.factories.config_factory import build_settings


def test_defaults_match_documented_values() -> None:
    """Ensure the default settings match the documented baseline configuration."""
    settings = build_settings(_env={})

    assert settings.llm_base_url == DEFAULT_LLM_BASE_URL
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.agent_timeout_seconds == DEFAULT_AGENT_TIMEOUT_SECONDS == 90
    assert settings.judge_confidence_threshold == DEFAULT_JUDGE_CONFIDENCE_THRESHOLD == 0.5
    assert settings.max_diff_lines == DEFAULT_MAX_DIFF_LINES == 800
    assert settings.dry_run is DEFAULT_DRY_RUN is False
    assert settings.log_level == "INFO"
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.github_token.get_secret_value() == ""
    assert settings.github_personal_access_token.get_secret_value() == ""
    assert settings.github_mcp_pr_tool is None
    assert settings.github_mcp_diff_tool is None
    assert settings.github_mcp_comment_tool is None


def test_environment_values_are_parsed_and_typed() -> None:
    """Verify environment values are loaded, trimmed, and converted to the right Python types."""
    settings = build_settings(
        _env={
            "LLM_BASE_URL": "https://example.test/v1/",
            "LLM_MODEL": "example-model",
            "LLM_API_KEY": "llm-secret",
            "GITHUB_TOKEN": "workflow-token",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "pat-token",
            "AGENT_TIMEOUT_SECONDS": "45",
            "JUDGE_CONFIDENCE_THRESHOLD": "0.75",
            "MAX_DIFF_LINES": "250",
            "DRY_RUN": "true",
            "LOG_LEVEL": "debug",
            "GITHUB_MCP_PR_TOOL": "pull_request_read",
            "GITHUB_MCP_DIFF_TOOL": "get_diff",
            "GITHUB_MCP_COMMENT_TOOL": "add_issue_comment",
        }
    )

    assert settings.llm_base_url == "https://example.test/v1/"
    assert settings.llm_model == "example-model"
    assert settings.llm_api_key.get_secret_value() == "llm-secret"
    assert settings.github_token.get_secret_value() == "workflow-token"
    assert settings.github_personal_access_token.get_secret_value() == "pat-token"
    assert settings.agent_timeout_seconds == 45
    assert settings.judge_confidence_threshold == 0.75
    assert settings.max_diff_lines == 250
    assert settings.dry_run is True
    assert settings.log_level == "DEBUG"
    assert settings.github_mcp_pr_tool == "pull_request_read"
    assert settings.github_mcp_diff_tool == "get_diff"
    assert settings.github_mcp_comment_tool == "add_issue_comment"


def test_explicit_keyword_arguments_override_environment() -> None:
    """Ensure explicit constructor arguments win over values read from the environment."""
    settings = build_settings(_env={"AGENT_TIMEOUT_SECONDS": "10"}, agent_timeout_seconds=30)

    assert settings.agent_timeout_seconds == 30


def test_blank_environment_values_fall_back_to_defaults() -> None:
    """Blank values should be ignored so defaults remain in effect."""
    settings = build_settings(
        _env={
            "LLM_MODEL": "  ",
            "AGENT_TIMEOUT_SECONDS": "",
            "MAX_DIFF_LINES": " ",
            "LOG_LEVEL": "",
        }
    )

    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.agent_timeout_seconds == DEFAULT_AGENT_TIMEOUT_SECONDS
    assert settings.max_diff_lines == DEFAULT_MAX_DIFF_LINES
    assert settings.log_level == "INFO"


def test_process_environment_is_read_without_explicit_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that os.environ is used when no mapping is passed in."""
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("DRY_RUN", "yes")

    settings = build_settings()

    assert settings.agent_timeout_seconds == 17
    assert settings.dry_run is True


def test_local_dotenv_is_loaded_and_real_environment_wins(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure .env values are loaded as fallbacks while real environment values win."""
    for variable in (
        "LLM_MODEL",
        "MAX_DIFF_LINES",
        "JUDGE_CONFIDENCE_THRESHOLD",
        "AGENT_TIMEOUT_SECONDS",
        "DRY_RUN",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(variable, raising=False)

    (tmp_path / ".env").write_text(
        "LLM_MODEL=dotenv-model\nMAX_DIFF_LINES=123\nDRY_RUN=true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = build_settings()
    assert settings.llm_model == "dotenv-model"
    assert settings.max_diff_lines == 123
    assert settings.dry_run is True

    monkeypatch.setenv("LLM_MODEL", "process-model")
    overridden = build_settings()
    assert overridden.llm_model == "process-model"
    assert overridden.max_diff_lines == 123


@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeout_must_be_positive(value: str) -> None:
    """Reject non-positive agent timeouts."""
    with pytest.raises(ValidationError):
        build_settings(_env={"AGENT_TIMEOUT_SECONDS": value})


@pytest.mark.parametrize("value", ["0", "-5"])
def test_max_diff_lines_must_be_positive(value: str) -> None:
    """Reject non-positive diff limits."""
    with pytest.raises(ValidationError):
        build_settings(_env={"MAX_DIFF_LINES": value})


@pytest.mark.parametrize("value", ["-0.01", "1.01"])
def test_confidence_threshold_must_be_within_zero_and_one(value: str) -> None:
    """Reject confidence thresholds outside the allowed range."""
    with pytest.raises(ValidationError):
        build_settings(_env={"JUDGE_CONFIDENCE_THRESHOLD": value})


def test_confidence_threshold_accepts_boundaries() -> None:
    """Accept the minimum and maximum legal confidence values."""
    assert build_settings(_env={"JUDGE_CONFIDENCE_THRESHOLD": "0"}).judge_confidence_threshold == 0
    assert build_settings(_env={"JUDGE_CONFIDENCE_THRESHOLD": "1"}).judge_confidence_threshold == 1


def test_invalid_log_level_is_rejected() -> None:
    """Reject unsupported log levels before the app starts."""
    with pytest.raises(ValidationError):
        build_settings(_env={"LOG_LEVEL": "verbose"})


def test_unknown_setting_is_rejected() -> None:
    """Reject extra environment fields that are not part of the settings schema."""
    with pytest.raises(ValidationError):
        build_settings(_env={}, unknown_field="value")


def test_settings_are_frozen() -> None:
    """Verify the settings model is immutable after initialization."""
    settings = build_settings(_env={})

    with pytest.raises(ValidationError):
        settings.max_diff_lines = 10


def test_secrets_are_redacted_in_repr_and_strings() -> None:
    """Ensure secret values are hidden from repr and string output."""
    token = "super-secret-token-value"
    settings = build_settings(
        _env={
            "LLM_API_KEY": token,
            "GITHUB_TOKEN": token,
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        }
    )

    assert token not in repr(settings)
    assert token not in str(settings)
    assert token not in str(settings.llm_api_key)
    assert token not in str(settings.github_token)
    assert token not in str(settings.github_personal_access_token)
    assert "llm_api_key" not in repr(settings)


def test_validation_errors_do_not_include_secret_values() -> None:
    """Check validation messages do not leak secret values."""
    token = "super-secret-token-value"

    with pytest.raises(ValidationError) as exc_info:
        build_settings(_env={"LLM_API_KEY": token, "AGENT_TIMEOUT_SECONDS": "0"})

    assert token not in str(exc_info.value)
