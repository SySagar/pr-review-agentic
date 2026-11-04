"""Tests for the deterministic validation checks."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.checks.ast_checks import run_ast_checks
from harness.checks.pr_checks import (
    check_pr_description,
    check_tests_touched,
    is_source_path,
    is_test_path,
)
from harness.checks.ruff_check import run_ruff_check
from harness.checks.rules import VALIDATION_RULES, get_rule, rule_catalog
from harness.checks.runner import run_checks
from tests.factories import build_diff_file, build_diff_info

CLEAN_SOURCE = '''"""Authentication helpers."""


def login(email: str) -> bool:
    """Return True when the email looks valid."""
    return "@" in email
'''

UNTYPED_SOURCE = '''"""Authentication helpers."""


def forgot_password(email):
    return email
'''


def _diff(*paths: str, lines: dict[str, tuple[int, ...]] | None = None):
    lines = lines or {}
    return build_diff_info(
        files=tuple(build_diff_file(path=path, changed_lines=lines.get(path, ())) for path in paths)
    )


def _completed(
    stdout: str = "[]",
    *,
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ruff"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _runner(
    stdout: str = "[]",
    *,
    returncode: int = 0,
    stderr: str = "",
    error: Exception | None = None,
):
    """Build a fake ruff runner and record its calls."""

    calls: list[tuple[list[str], Path]] = []

    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        if error is not None:
            raise error
        return _completed(stdout, returncode=returncode, stderr=stderr)

    return runner, calls


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _diagnostic(**overrides) -> str:
    data = {
        "code": "F401",
        "message": "`os` imported but unused",
        "filename": "app/auth.py",
        "location": {"row": 1, "column": 8},
        "end_location": {"row": 1, "column": 10},
    }
    data.update(overrides)
    return json.dumps([data])


def test_clean_changed_file_produces_no_findings(tmp_path: Path):
    """A typed, documented function with a test change and a description is clean."""
    _write(tmp_path, "app/auth.py", CLEAN_SOURCE)
    _write(tmp_path, "tests/test_auth.py", "def test_login():\n    pass\n")
    runner, _ = _runner()

    findings = run_checks(
        _diff("app/auth.py", "tests/test_auth.py", lines={"app/auth.py": (4,)}),
        pr_body="Add a login helper.",
        repo_root=tmp_path,
        ruff_runner=runner,
    )

    assert findings == []


def test_missing_type_hints_and_docstring_are_reported(tmp_path: Path):
    """A new public function without hints or a docstring yields both findings."""
    _write(tmp_path, "app/auth.py", UNTYPED_SOURCE)
    _write(tmp_path, "tests/test_auth.py", "def test_reset():\n    pass\n")
    runner, _ = _runner()

    findings = run_checks(
        _diff("app/auth.py", "tests/test_auth.py", lines={"app/auth.py": (4,)}),
        pr_body="Add password reset.",
        repo_root=tmp_path,
        ruff_runner=runner,
    )

    assert [finding.file for finding in findings] == ["app/auth.py", "app/auth.py"]
    assert [finding.line for finding in findings] == [4, 4]
    assert "type hints" in findings[0].issue
    assert "docstring" in findings[1].issue
    assert all(finding.severity == "low" for finding in findings)


def test_private_and_unchanged_functions_are_ignored(tmp_path: Path):
    """Private helpers and pre-existing definitions are not this PR's responsibility."""
    source = '''"""Helpers."""


def _private(value):
    return value


def old_public(value):
    return value


def new_public(value: str) -> str:
    """Return the value."""
    return value
'''
    _write(tmp_path, "app/helpers.py", source)
    _write(tmp_path, "tests/test_helpers.py", "def test_new():\n    pass\n")
    runner, _ = _runner()

    findings = run_checks(
        _diff("app/helpers.py", "tests/test_helpers.py", lines={"app/helpers.py": (13,)}),
        pr_body="Add a public helper.",
        repo_root=tmp_path,
        ruff_runner=runner,
    )

    assert findings == []


def test_class_methods_are_checked_but_dunders_are_skipped(tmp_path: Path):
    """Public methods are checked; dunder methods are treated as not public."""
    source = '''"""Service module."""


class Service:
    def __init__(self, name):
        self.name = name

    def public(self):
        return self.name

    def typed(self, value: str) -> str:
        """Return the value."""
        return value
'''
    findings = run_ast_checks(
        {"app/service.py": source},
        {"app/service.py": (8, 11)},
    )

    assert [(finding.line, "type hints" in finding.issue) for finding in findings] == [
        (8, True),
        (8, False),
    ]


def test_async_functions_are_checked(tmp_path: Path):
    """Async public functions receive the same hint and docstring checks."""
    source = '''"""Async helpers."""


async def fetch(url):
    return url
'''
    findings = run_ast_checks({"app/fetch.py": source}, {"app/fetch.py": (4,)})

    assert len(findings) == 2
    assert all(finding.line == 4 for finding in findings)


def test_ruff_diagnostics_become_findings():
    """Ruff JSON diagnostics are converted with their code, line, and file."""
    runner, calls = _runner(_diagnostic())

    findings = run_ruff_check(["app/auth.py"], cwd=Path("."), runner=runner)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.file == "app/auth.py"
    assert finding.line == 1
    assert finding.issue == "F401: `os` imported but unused"
    assert finding.severity == "medium"
    assert finding.confidence == 1.0
    assert calls[0][0] == [
        "ruff",
        "check",
        "--output-format",
        "json",
        "app/auth.py",
    ]


def test_ruff_absolute_filename_is_made_relative(tmp_path: Path):
    """Absolute ruff filenames are converted to repo-relative POSIX paths."""
    runner, _ = _runner(_diagnostic(filename=str(tmp_path / "app" / "auth.py")))

    findings = run_ruff_check(["app/auth.py"], cwd=tmp_path, runner=runner)

    assert findings[0].file == "app/auth.py"


def test_ruff_exit_code_crash_becomes_an_error_finding():
    """A ruff crash (exit 2) is reported as a finding, not raised."""
    runner, _ = _runner(returncode=2, stderr="diagnostic parse error")

    findings = run_ruff_check(["app/auth.py"], cwd=Path("."), runner=runner)

    assert len(findings) == 1
    assert "ruff check failed (exit 2)" in findings[0].issue
    assert "diagnostic parse error" in findings[0].issue


def test_missing_ruff_binary_becomes_an_error_finding():
    """An OSError from the subprocess boundary is reported as a finding."""
    runner, _ = _runner(error=FileNotFoundError("ruff not found"))

    findings = run_ruff_check(["app/auth.py"], cwd=Path("."), runner=runner)

    assert len(findings) == 1
    assert "could not run" in findings[0].issue


def test_ruff_invalid_json_becomes_an_error_finding():
    """Unparseable ruff output is reported instead of crashing the run."""
    runner, _ = _runner("not json")

    findings = run_ruff_check(["app/auth.py"], cwd=Path("."), runner=runner)

    assert len(findings) == 1
    assert "invalid JSON" in findings[0].issue


def test_non_python_files_are_skipped(tmp_path: Path):
    """Non-Python changes never invoke ruff and produce no findings."""
    runner, calls = _runner()

    findings = run_checks(
        _diff("README.md", lines={"README.md": (1,)}),
        pr_body="Update the docs.",
        repo_root=tmp_path,
        ruff_runner=runner,
    )

    assert findings == []
    assert calls == []


def test_source_change_without_a_test_is_flagged():
    """A Python source change with no test change produces a tests-touched finding."""
    runner, _ = _runner()

    findings = run_checks(
        _diff("app/auth.py", lines={"app/auth.py": (4,)}),
        pr_body="Add password reset.",
        sources={"app/auth.py": CLEAN_SOURCE},
        ruff_runner=runner,
    )

    assert len(findings) == 1
    assert findings[0].file == "app/auth.py"
    assert findings[0].line is None
    assert "no test file" in findings[0].issue


def test_changed_test_file_suppresses_the_tests_finding():
    """A touched test file means the tests-touched finding is not emitted."""
    runner, _ = _runner()

    assert check_tests_touched(["app/auth.py", "tests/test_auth.py"]) == []
    run_checks(
        _diff("app/auth.py", "tests/test_auth.py", lines={"app/auth.py": (4,)}),
        pr_body="Add password reset.",
        sources={"app/auth.py": CLEAN_SOURCE},
        ruff_runner=runner,
    )


def test_empty_description_is_flagged():
    """A blank PR body produces a description finding on the first changed file."""
    runner, _ = _runner()

    findings = run_checks(
        _diff("app/auth.py", "tests/test_auth.py", lines={"app/auth.py": (4,)}),
        pr_body="   \n",
        sources={"app/auth.py": CLEAN_SOURCE},
        ruff_runner=runner,
    )

    assert len(findings) == 1
    assert findings[0].file == "app/auth.py"
    assert findings[0].issue == "PR description is empty."


def test_missing_description_is_flagged():
    """A ``None`` PR body is treated as empty."""
    findings = check_pr_description(None, fallback_file="app/auth.py")

    assert len(findings) == 1
    assert findings[0].file == "app/auth.py"


def test_syntax_error_is_skipped_without_crashing():
    """Invalid Python is skipped by the AST checks instead of aborting the run."""
    findings = run_ast_checks({"app/broken.py": "def ("}, {"app/broken.py": (1,)})

    assert findings == []


def test_unchanged_lines_are_not_checked():
    """Public functions whose def line is outside the diff are ignored."""
    findings = run_ast_checks({"app/auth.py": UNTYPED_SOURCE}, {"app/auth.py": (99,)})

    assert findings == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_auth.py", True),
        ("test_auth.py", True),
        ("app/auth_test.py", True),
        ("tests/conftest.py", True),
        ("app/auth.py", False),
        ("README.md", False),
    ],
)
def test_is_test_path(path: str, expected: bool):
    """Test-file detection covers common pytest layouts."""
    assert is_test_path(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/auth.py", True),
        ("scripts/tool.py", True),
        ("tests/test_auth.py", False),
        ("README.md", False),
    ],
)
def test_is_source_path(path: str, expected: bool):
    """Source detection is Python-only and excludes tests."""
    assert is_source_path(path) is expected


def test_rules_are_centralized_and_catalog_is_serializable():
    """All five rules are present with stable keys and plain-data catalog output."""
    assert [rule.key for rule in VALIDATION_RULES] == [
        "ruff",
        "type_hints",
        "docstrings",
        "tests_touched",
        "pr_description",
    ]
    assert get_rule("ruff").severity == "medium"
    catalog = rule_catalog()
    assert len(catalog) == 5
    assert catalog[0] == {
        "key": "ruff",
        "title": "ruff passes on changed Python files",
        "severity": "medium",
    }


def test_unknown_rule_id_raises_key_error():
    """Looking up an unknown rule fails loudly."""
    with pytest.raises(KeyError, match="unknown validation rule"):
        get_rule("nope")


@pytest.mark.integration
def test_real_ruff_reports_an_unused_import(tmp_path: Path):
    """Optional integration check against the real ruff binary."""
    if shutil.which("ruff") is None:
        pytest.skip("ruff is not installed")

    _write(tmp_path, "app/auth.py", "import os\n")
    _write(tmp_path, "tests/test_auth.py", "def test_nothing():\n    pass\n")

    findings = run_checks(
        _diff("app/auth.py", "tests/test_auth.py", lines={"app/auth.py": (1,)}),
        pr_body="Add an import.",
        repo_root=tmp_path,
    )

    assert any("F401" in finding.issue for finding in findings)
