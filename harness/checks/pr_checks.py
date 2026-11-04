"""PR-level deterministic checks: tests touched and description presence."""

from __future__ import annotations

from collections.abc import Iterable

from harness.checks.rules import ValidationRule, get_rule
from harness.schemas import Finding

__all__ = [
    "check_pr_description",
    "check_tests_touched",
    "is_source_path",
    "is_test_path",
]


def is_test_path(path: str) -> bool:
    """Return True when ``path`` looks like a test file."""

    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if not parts:
        return False
    name = parts[-1]
    return (
        any(part in {"tests", "test"} for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def is_source_path(path: str) -> bool:
    """Return True for Python source files that are not tests."""

    return path.endswith(".py") and not is_test_path(path)


def check_tests_touched(
    changed_paths: Iterable[str],
    *,
    rule: ValidationRule | None = None,
) -> list[Finding]:
    """Flag source changes that arrive without any test file change."""

    rule = rule or get_rule("tests_touched")
    paths = list(changed_paths)
    source_paths = [path for path in paths if is_source_path(path)]
    if not source_paths or any(is_test_path(path) for path in paths):
        return []

    return [
        Finding(
            file=source_paths[0],
            line=None,
            severity=rule.severity,
            confidence=1.0,
            issue="Source files changed but no test file was added or modified.",
            suggested_fix="Add or update a test that covers the changed source.",
        )
    ]


def check_pr_description(
    body: str | None,
    *,
    fallback_file: str = "",
    rule: ValidationRule | None = None,
) -> list[Finding]:
    """Flag an empty or whitespace-only PR description."""

    rule = rule or get_rule("pr_description")
    if body is not None and body.strip():
        return []

    return [
        Finding(
            file=fallback_file,
            line=None,
            severity=rule.severity,
            confidence=1.0,
            issue="PR description is empty.",
            suggested_fix="Describe what the PR changes and why it is needed.",
        )
    ]
