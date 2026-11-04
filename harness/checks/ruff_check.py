"""Run ruff on changed Python files and convert its JSON diagnostics to findings."""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from harness.checks.rules import ValidationRule, get_rule
from harness.schemas import Finding

logger = logging.getLogger(__name__)

__all__ = ["RuffRunner", "run_ruff_check"]

# Injectable subprocess boundary so unit tests never need a real ruff binary.
RuffRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]

_RUFF_TIMEOUT_SECONDS = 120


def run_ruff_check(
    python_paths: Sequence[str],
    *,
    cwd: Path,
    rule: ValidationRule | None = None,
    runner: RuffRunner | None = None,
) -> list[Finding]:
    """Lint ``python_paths`` with ruff and return one finding per diagnostic.

    A missing binary, a crash, or unparseable output becomes a single error
    finding instead of an exception so the review pipeline keeps going.
    """

    rule = rule or get_rule("ruff")
    paths = [path for path in python_paths if path.endswith(".py")]
    if not paths:
        return []

    command = ["ruff", "check", "--output-format", "json", *paths]
    completed = _invoke(runner or _run, command, cwd)
    if isinstance(completed, Finding):
        return [completed]
    if completed.returncode >= 2:
        detail = (completed.stderr or completed.stdout or "").strip()
        logger.warning("ruff failed with exit code %d", completed.returncode)
        return [
            _error_finding(
                rule,
                f"ruff check failed (exit {completed.returncode}): {detail[:500]}",
            )
        ]

    try:
        diagnostics = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        logger.warning("ruff returned invalid JSON: %s", exc)
        return [_error_finding(rule, f"ruff returned invalid JSON: {exc}")]
    if not isinstance(diagnostics, list):
        logger.warning("ruff returned a non-list JSON payload")
        return [_error_finding(rule, "ruff returned an unexpected JSON payload")]

    findings = [
        finding
        for diagnostic in diagnostics
        if (finding := _to_finding(diagnostic, rule, cwd)) is not None
    ]
    logger.info("ruff checked %d file(s): %d finding(s)", len(paths), len(findings))
    return findings


def _invoke(
    runner: RuffRunner,
    command: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str] | Finding:
    """Call the runner, converting transport failures into an error finding."""

    try:
        return runner(command, cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ruff could not run: %s", exc)
        return _error_finding(
            get_rule("ruff"),
            f"ruff check could not run: {exc}",
        )


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Default runner: the real ruff binary with a bounded timeout."""

    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_RUFF_TIMEOUT_SECONDS,
        check=False,
    )


def _to_finding(
    diagnostic: object,
    rule: ValidationRule,
    cwd: Path,
) -> Finding | None:
    """Convert one ruff JSON diagnostic; ignore entries with the wrong shape."""

    if not isinstance(diagnostic, dict):
        return None
    filename = diagnostic.get("filename")
    message = diagnostic.get("message")
    if not isinstance(filename, str) or not isinstance(message, str):
        return None

    code = diagnostic.get("code")
    label = f"{code}: " if isinstance(code, str) and code else ""
    return Finding(
        file=_display_path(filename, cwd),
        line=_diagnostic_line(diagnostic),
        severity=rule.severity,
        confidence=1.0,
        issue=f"{label}{message}",
        suggested_fix="",
    )


def _diagnostic_line(diagnostic: dict[object, object]) -> int | None:
    """Read ``location.row`` from a diagnostic when it is a valid integer."""

    location = diagnostic.get("location")
    if not isinstance(location, dict):
        return None
    row = location.get("row")
    return row if isinstance(row, int) else None


def _display_path(filename: str, cwd: Path) -> str:
    """Return a repo-relative POSIX path for a ruff diagnostic filename."""

    path = Path(filename)
    if path.is_absolute():
        try:
            path = path.relative_to(cwd)
        except ValueError:
            pass
    return path.as_posix()


def _error_finding(rule: ValidationRule, issue: str) -> Finding:
    """Build the finding that reports a failed ruff invocation."""

    return Finding(
        file="",
        line=None,
        severity=rule.severity,
        confidence=1.0,
        issue=issue,
        suggested_fix="Run ruff manually and fix the configuration or installation.",
    )
