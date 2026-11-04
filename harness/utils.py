"""Shared helper utilities used across the review harness."""

from __future__ import annotations

import time

from pydantic import BaseModel

from harness.schemas import Finding

MAX_ERROR_CHARS = 500
REMOVED_MARKER_PLACEHOLDER = "[removed-boundary-marker]"

__all__ = [
    "MAX_ERROR_CHARS",
    "REMOVED_MARKER_PLACEHOLDER",
    "describe_error",
    "elapsed_ms",
    "extract_findings",
    "retry_prompt",
    "sanitize_untrusted_text",
    "truncate_text",
]


def sanitize_untrusted_text(
    value: str,
    *,
    start_marker: str,
    end_marker: str,
    placeholder: str = REMOVED_MARKER_PLACEHOLDER,
) -> str:
    """Normalize untrusted PR content before embedding it in a boundary block."""

    if not value:
        return "(empty)"

    return value.replace(start_marker, placeholder).replace(end_marker, placeholder)


def truncate_text(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    """Keep error text bounded so it cannot flood logs or the final comment."""

    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def describe_error(
    exc: BaseException,
    *,
    prefix: str | None = None,
    limit: int = MAX_ERROR_CHARS,
) -> str:
    """Build a short, bounded error description with the exception class."""

    detail = str(exc).strip()
    text = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    if prefix:
        text = f"{prefix} ({text})"
    return truncate_text(text, limit=limit)


def retry_prompt(user_prompt: str, error: str, *, limit: int = MAX_ERROR_CHARS) -> str:
    """Append the validation error to the prompt for the single retry."""

    return (
        f"{user_prompt}\n\n"
        "The previous response was rejected by the output validator.\n"
        f"Validation error:\n{truncate_text(error, limit=limit)}\n\n"
        "Return one corrected JSON object only. Do not add prose or Markdown fences."
    )


def extract_findings(output: BaseModel, findings_field: str) -> list[Finding]:
    """Return validated findings from an agent output model."""

    value = getattr(output, findings_field, None)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{findings_field} must be a list")

    findings: list[Finding] = []
    for item in value:
        if isinstance(item, Finding):
            findings.append(item)
        else:
            findings.append(Finding.model_validate(item))
    return findings


def elapsed_ms(started: float) -> int:
    """Return elapsed wall-clock time in whole milliseconds."""

    return int((time.perf_counter() - started) * 1000)
