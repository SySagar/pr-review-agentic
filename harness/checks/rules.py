"""Configurable policy for the deterministic validation checks.

The five v1 rules and their severities live here so policy can be tuned in one
place without touching the check implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.schemas import Severity

__all__ = ["VALIDATION_RULES", "ValidationRule", "get_rule", "rule_catalog"]


@dataclass(frozen=True)
class ValidationRule:
    """One validation check, its stable key, and the severity it reports."""

    key: str
    title: str
    severity: Severity


VALIDATION_RULES: tuple[ValidationRule, ...] = (
    ValidationRule("ruff", "ruff passes on changed Python files", Severity.medium),
    ValidationRule("type_hints", "New public functions have type hints", Severity.low),
    ValidationRule("docstrings", "New public functions have docstrings", Severity.low),
    ValidationRule("tests_touched", "Source changes include a test file change", Severity.medium),
    ValidationRule("pr_description", "PR description is non-empty", Severity.low),
)

_RULES_BY_KEY = {rule.key: rule for rule in VALIDATION_RULES}


def get_rule(rule_key: str) -> ValidationRule:
    """Return the configured rule with ``rule_key``.

    Raises:
        KeyError: If no rule with that key is configured.
    """

    try:
        return _RULES_BY_KEY[rule_key]
    except KeyError:
        raise KeyError(f"unknown validation rule: {rule_key}") from None


def rule_catalog() -> list[dict[str, str]]:
    """Return the rules as plain data for other processes and MCP tools."""

    return [
        {"key": rule.key, "title": rule.title, "severity": rule.severity.value}
        for rule in VALIDATION_RULES
    ]
